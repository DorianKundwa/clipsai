import json, subprocess
from datetime import datetime
from pathlib import Path

from clipsai import Transcription, build_cues, burn_captions
from clipsai.ai import (AIClipFinder, package_clip, translate_cues, suggest_edits,
                        apply_edits, burn_hook, create_thumbnail)

SENTENCES = [
    "Most people get this completely wrong about short videos.",
    "The first three seconds decide whether anyone keeps watching.",
    "I tested forty clips last month and the numbers were brutal.",
    "Hooks with a number held twice as many viewers.",
]

def transcription():
    char_info, t = [], 0.0
    for sentence in SENTENCES:
        for word in sentence.split(" "):
            for ch in word:
                char_info.append({"char": ch, "start_time": round(t, 3), "end_time": round(t + 0.09, 3), "speaker": 0})
                t += 0.09
            char_info.append({"char": " ", "start_time": None, "end_time": None, "speaker": 0})
            t += 0.14
    return Transcription({"source_software": "smoke", "time_created": datetime.now(), "language": "en", "num_speakers": 1, "char_info": char_info})

class Stub:
    def __init__(self, payloads): self.payloads = list(payloads)
    def assert_ready(self): pass
    def complete(self, prompt, **kw): return "ready"
    def complete_json(self, prompt, **kw): return self.payloads.pop(0)

tr = transcription()
print("transcript duration", round(tr.end_time, 2))

finder = AIClipFinder(
    client=Stub([
        {"scores": [{"id": "window_001", "score": 92, "reason": "concrete numbers"}]},
        {"shorts": [{"start": 0.5, "end": 3.5, "predicted_score": 91,
                     "viral_hook_text": "40 clips, 2x viewers", 
                     "video_title_for_youtube_short": "The 3-second hook rule"}]},
    ]),
    min_clip_duration=2, max_clip_duration=8, max_clips=3)
clips = finder.find_clips(tr)
print("ai clips", [(c.start_time, c.end_time, c.score, c.hook) for c in clips])
assert clips and 2 <= clips[0].duration <= 8.5

meta = package_clip(Stub([{"title": "The 3-second hook rule", "hook": "40 clips, 2x viewers",
                           "youtube_titles": ["The 3-second hook rule"],
                           "hashtags": ["#editing", "#shorts"]}]), tr, clips[0].start_time, clips[0].end_time)
print("metadata", meta["hook"], meta["hashtags"])

cues = build_cues(tr, clips[0].start_time, clips[0].end_time)
translated = translate_cues(Stub([{"lines": [{"i": 1, "text": "Hola"}]}]), cues[:1], "Spanish")
print("translated", translated[0].text, translated[0].start, translated[0].end)

edits = suggest_edits(Stub([{"edits": [{"type": "color_pop", "start": 0.3, "end": 1.5, "strength": 0.4}]}]),
                      "transcript text", duration=6.0)
print("edits", edits)

src = "sandbox/captions_smoke/in.mp4"
Path("sandbox/ai_out").mkdir(exist_ok=True)
hook_video = burn_hook(src, meta["hook"], "sandbox/ai_out/hook.mp4", style="box")
thumb = create_thumbnail(src, meta["hook"], "sandbox/ai_out/thumb.jpg", position="left")
effects_video, applied = apply_edits(src, edits, "sandbox/ai_out/effects.mp4", has_captions=False)
capped = burn_captions(hook_video, cues, "sandbox/ai_out/hook_captions.mp4", preset="bold")

for path in (hook_video, thumb, effects_video, capped):
    data = Path(path).read_bytes()
    print("file", path, len(data), "bytes")
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path], capture_output=True, text=True)
    print("  duration", probe.stdout.strip(), "applied", len(applied) if path == effects_video else "")
print("SMOKE_OK")
