from faster_whisper import WhisperModel
import json
m = WhisperModel("small", device="cpu", compute_type="int8")
segs, info = m.transcribe("work/audio.wav", vad_filter=False, language=None, beam_size=1)
out = []
for s in segs:
    out.append({"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text})
json.dump({"lang": info.language, "prob": info.language_probability, "segments": out},
          open("work/transcript.json", "w"), ensure_ascii=False, indent=1)
print(info.language)
for s in out:
    print(s["start"], s["end"], s["text"])
