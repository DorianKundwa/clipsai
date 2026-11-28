import os
import subprocess

import pytest

from clipsai.ai.effects import build_filter_string, build_punch_in_filter
from clipsai.ai.hooks import HOOK_POSITIONS, render_hook_png
from clipsai.captions.captions import CaptionCue, CaptionWord, to_ass
from clipsai.render import (
    EXPORT_PROFILES,
    CropWindow,
    RenderError,
    build_export_command,
    build_export_filter,
    export_clip,
    parse_crop,
    verify_output,
)
from clipsai.typography import (
    FONT_CATALOG,
    FontError,
    available_fonts,
    font_family,
    load_font,
    resolve_font,
)


def _cues():
    return [
        CaptionCue(
            [
                CaptionWord("FIRST", 0.2, 0.7),
                CaptionWord("LINE", 0.7, 1.2),
                CaptionWord("WORDS", 1.2, 1.8),
            ]
        )
    ]


def test_bundled_fonts_resolve_for_pillow_and_libass():
    keys = {face["key"] for face in available_fonts()}
    assert {"montserrat-extrabold", "archivo-black", "noto-serif"} <= keys
    for key in ("montserrat-extrabold", "archivo-black", "noto-serif"):
        assert os.path.isfile(resolve_font(key))
        assert load_font(48, key).getlength("HOOK") > 0
    assert font_family("archivo-black") == "Archivo Black"
    assert font_family("Arial") == "Arial"
    assert font_family("Some Installed Family") == "Some Installed Family"


def test_unknown_font_can_still_be_named_as_a_family():
    assert font_family("Helvetica Neue") == "Helvetica Neue"
    with pytest.raises(FontError):
        resolve_font("definitely-not-a-font")


def test_hook_card_kicker_adds_a_line_and_the_accent_rule():
    plain = render_hook_png("Coolest white boy since Mac Miller", width=1080)
    card = render_hook_png(
        "Coolest white boy since Mac Miller",
        width=1080,
        style="card",
        kicker="Who knew Ad-Rock's son could rap?",
    )
    assert card.height > plain.height
    # The card's top rule is yellow, the same accent the captions use.
    assert card.getpixel((card.width // 2, 1))[0] > 200
    assert card.getpixel((card.width // 2, 1))[1] > 150


def test_hook_positions_are_named_bands():
    assert set(HOOK_POSITIONS) == {"top", "upper", "center", "lower", "bottom"}
    assert 0 < HOOK_POSITIONS["upper"] < HOOK_POSITIONS["bottom"] < 1


def test_crop_window_parses_and_rejects_impossible_frames():
    window = parse_crop("0,0.28,0,0")
    assert window == CropWindow(bottom=0.28)
    assert "crop=" in window.filter()
    assert parse_crop("") is None
    with pytest.raises(RenderError):
        parse_crop("0,0.9,0,0")
    with pytest.raises(RenderError):
        CropWindow(top=0.4, bottom=0.4).validate()


def test_export_graph_covers_each_fill_mode():
    blur = build_export_filter("shorts", pad="blur")
    assert "split=2" in blur and "boxblur=28:2" in blur
    assert "fps=60" in blur and blur.endswith("[v]")

    crop = build_export_filter("reels", pad="crop")
    assert "force_original_aspect_ratio=increase" in crop and "pad=" not in crop

    black = build_export_filter("shorts", pad="black")
    assert "pad=1080:1920" in black and "color=black" in black


def test_export_graph_applies_crop_grade_and_punch_ins():
    graph = build_export_filter(
        "shorts",
        pad="blur",
        grade="punchy",
        crop=CropWindow(bottom=0.28),
        punch_ins=[1.0, 3.5],
    )
    assert graph.startswith("[0:v]crop=")
    assert "eq=contrast=1.09" in graph
    assert "zoompan" in graph and "between(on," in graph


def test_export_command_targets_the_campaign_master_spec():
    argv = build_export_command("in.mp4", "out.mp4", "shorts", grade="warm")
    text = " ".join(argv)
    assert "-b:v 12M" in text
    assert "-c:a aac" in text and "-ar 48000" in text
    assert "loudnorm=I=-14:TP=-1.5" in text
    assert "-profile:v high" in text and "-level 4.2" in text
    assert "-movflags +faststart" in text


def test_punch_in_filter_is_a_102_to_108_cadence():
    graph = build_punch_in_filter([1.0, 4.0], fps=60, width=1080, height=1920)
    assert graph.startswith("zoompan=z='1.0200+")
    assert graph.count("between(on,") == 2
    assert "s=1080x1920" in graph


def test_effect_plan_supports_the_new_looks_without_breaking_zoom_guard():
    edits = [
        {"type": "warm", "start": 0.5, "end": 2.0, "strength": 0.6},
        {"type": "grain", "start": 2.0, "end": 3.0, "strength": 0.4},
        {"type": "shake", "start": 3.0, "end": 3.4, "strength": 0.8},
        {"type": "cool", "start": 4.0, "end": 5.0, "strength": 0.4},
    ]
    graph, applied = build_filter_string(edits, 6.0, 30, 1080, 1920)
    assert [item["type"] for item in applied] == ["warm", "grain", "shake", "cool"]
    assert "colorbalance" in graph and "noise=alls=" in graph
    assert "scale=1080:1920" in graph

    guarded, guarded_applied = build_filter_string(
        [{"type": "punch_in", "start": 1.0, "end": 2.0}], 6.0, 30, 1080, 1920,
        has_captions=True,
    )
    assert guarded is None and guarded_applied == []


def test_burn_hook_is_timed_and_keeps_the_clip(tmp_path, sample_video):
    from clipsai.ai.hooks import burn_hook

    out = tmp_path / "hooked.mp4"
    burn_hook(
        sample_video,
        "Coolest white boy since Mac Miller",
        str(out),
        style="card",
        position="upper",
        kicker="Who knew Ad-Rock's son could rap?",
        start=0.0,
        end=1.0,
        fade=0.2,
    )
    assert out.is_file()
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(out)],
        capture_output=True,
        text=True,
    )
    assert abs(float(probe.stdout.strip()) - 3.0) < 0.1
    assert (tmp_path / "hooked.hook.png").is_file()


def test_caption_preset_is_embedded_in_the_master_ass():
    ass = to_ass(_cues(), preset="kinetic", width=1080, height=1920)
    assert "Montserrat ExtraBold,52," in ass
    assert "PlayResY: 1920" in ass


@pytest.fixture(scope="module")
def sample_video(tmp_path_factory):
    path = tmp_path_factory.mktemp("render") / "source.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i", "testsrc2=s=640x360:d=3:r=30",
            "-f", "lavfi", "-i", "sine=frequency=330:duration=3",
            "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
            str(path),
        ],
        check=True,
    )
    return str(path)


def test_export_writes_a_verified_master(tmp_path, sample_video):
    out = tmp_path / "master.mp4"
    export_clip(sample_video, str(out), "square", pad="blur", grade="punchy")
    assert out.is_file()
    report = verify_output(str(out), "square")
    assert report["ok"], [c for c in report["checks"] if not c["ok"]]
    stats = report["stats"]
    assert (stats["width"], stats["height"]) == (1080, 1080)
    assert stats["fps"] == 30.0
    assert stats["audio_rate"] == 48000
    assert abs(report["loudness"]["integrated"] + 14) <= 1.0


def test_profiles_expose_the_platform_specs():
    assert EXPORT_PROFILES["shorts"].fps == 60.0
    assert EXPORT_PROFILES["shorts"].video_bitrate == "12M"
    assert EXPORT_PROFILES["reels"].max_seconds == 90.0
    assert EXPORT_PROFILES["youtube"].width == 1920
    assert FONT_CATALOG["montserrat-extrabold"].bundled is True
