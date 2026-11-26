from faster_whisper import WhisperModel
import json
m = WhisperModel("base", device="cpu", compute_type="int8")
segs, info = m.transcribe("reddit_reviews_assets/Sizzle Video.mp4", vad_filter=True)
out = [{"start": round(s.start,2), "end": round(s.end,2), "text": s.text.strip()} for s in segs]
json.dump({"language": info.language, "segments": out}, open("rr_audio/asr.json","w"), indent=2)
print(json.dumps(out, indent=1)[:1500])
