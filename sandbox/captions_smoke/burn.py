import subprocess, json
from datetime import datetime
from pathlib import Path
from clipsai import Transcription, build_cues, burn_captions

words = ["This", "is", "the", "ClipsAI", "caption", "smoke", "test"]
char_info, t = [], 0.0
for w in words:
    for ch in w:
        char_info.append({"char": ch, "start_time": round(t, 3), "end_time": round(t + 0.12, 3), "speaker": 0})
        t += 0.16
    char_info.append({"char": " ", "start_time": None, "end_time": None, "speaker": 0})
    t += 0.25

tr = Transcription({
    "source_software": "smoke", "time_created": datetime.now(), "language": "en",
    "num_speakers": 1, "char_info": char_info,
})
cues = build_cues(tr, preset="bold")
print("cues:", [(round(c.start, 2), round(c.end, 2), c.text) for c in cues])
out = burn_captions("sandbox/captions_smoke/in.mp4", cues, "sandbox/captions_smoke/out.mp4", preset="bold")
probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height", "-of", "json", out], capture_output=True, text=True)
print(probe.stdout)
Path("sandbox/captions_smoke/out.mp4").stat()
