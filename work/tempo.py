import wave, numpy as np, json
w = wave.open("work/audio.wav","rb"); sr=w.getframerate()
x = np.frombuffer(w.readframes(w.getnframes()),dtype=np.int16).astype(np.float32)/32768.0
hop=256
n=(len(x)-1024)//hop
frames=np.lib.stride_tricks.sliding_window_view(x,(1024,))[::hop][:n]
S=np.abs(np.fft.rfft(frames*np.hanning(1024),axis=1))[:,:200]
flux=np.maximum(0,np.diff(S,axis=0)).sum(1)
flux-=flux.mean()
fps=sr/hop
ac=np.correlate(flux,flux,'full')[len(flux)-1:]
lo,hi=int(0.3*fps),int(1.2*fps)
lag=lo+int(np.argmax(ac[lo:hi]))
bpm=60*fps/lag
print("fps",round(fps,2),"lag",lag,"bpm",round(bpm,2),"bpm/2",round(bpm/2,2))
# refine with harmonics
cands={}
for mult in (1,2,4):
    L=int(round(lag*mult))
    if L+5<len(ac): cands[mult]=round(60*fps/L,2)
print("candidate bpms",cands)
# strongest onset times snapped to grid
beats=[]
t=0.0
period=lag/fps
print("period",round(period,4))
np.save("work/flux.npy",flux)
json.dump({"bpm":bpm,"period":period},open("work/tempo.json","w"))
# per-second spectral centroid and low-band energy
low=S[:,:12].sum(1); high=S[:,60:].sum(1)
sec=int(fps)
print("\nsec low high ratio")
for i in range(0,len(low)//sec):
    print(i, int(low[i*sec:(i+1)*sec].mean()), int(high[i*sec:(i+1)*sec].mean()))
