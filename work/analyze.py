import wave, numpy as np, json

w = wave.open("work/audio.wav", "rb")
sr = w.getframerate()
data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
mono = data
dur = len(mono) / sr

win = int(0.25 * sr)
hop = int(0.25 * sr)
n = (len(mono) - win) // hop
rms = np.array([np.sqrt(np.mean(mono[i*hop:i*hop+win]**2)) for i in range(n)])
db = 20*np.log10(np.maximum(rms, 1e-6))

# spectral flux (onsets) per 50ms
sp_win = int(0.05*sr)
n2 = (len(mono)-sp_win)//sp_win
mag = np.zeros((n2, 256), dtype=np.float32)
hann = np.hanning(sp_win)
for i in range(n2):
    seg = mono[i*sp_win:i*sp_win+sp_win]*hann
    mag[i] = np.abs(np.fft.rfft(seg))[:256]
flux = np.maximum(0, np.diff(mag, axis=0)).sum(axis=1)

print("duration", round(dur,2), "sr", sr)
print("\n--- loudness (dB RMS) per 5s ---")
for t in range(0, int(dur), 5):
    seg = db[t*4:(t+5)*4]
    print(f"{t:>4}s {seg.mean():6.1f}  max {seg.max():6.1f}")

print("\n--- top transient windows (0.25s bins, flux) ---")
fbin = 5  # 0.25s
nb = len(flux)//fbin
fb = flux[:nb*fbin].reshape(nb, fbin).mean(axis=1)
order = np.argsort(fb)[::-1]
seen = []
for idx in order:
    t = idx*0.25
    if all(abs(t-s) > 1.5 for s in seen):
        seen.append(t)
    if len(seen) >= 40: break
print(sorted(round(x,2) for x in seen))

# energy peaks
print("\n--- loudest 1s windows ---")
w2 = sr
n3 = len(mono)//w2
e = np.array([np.sqrt(np.mean(mono[i*w2:(i+1)*w2]**2)) for i in range(n3)])
order = np.argsort(e)[::-1]
seen=[]
for idx in order:
    if all(abs(idx-s) > 3 for s in seen): seen.append(idx)
    if len(seen) >= 25: break
print(sorted(seen))
np.save("work/rms.npy", db)
