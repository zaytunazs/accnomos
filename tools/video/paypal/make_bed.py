# ruff: noqa
# fmt: off
# Original music bed, synthesised here (no samples, no third-party recording): warm pad + soft plucks, 90 bpm.
import numpy as np, wave
sr=44100; bpm=90; beat=60/bpm; bar=4*beat; total=162.0
n=int(sr*total); L=np.zeros(n); R=np.zeros(n)
def f(m): return 440*2**((m-69)/12)
prog=[[48,55,60,64,67],[45,52,57,60,64],[41,48,57,60,65],[43,50,55,59,62]]  # C, Am, F, G (add colour tones)
rng=np.random.default_rng(7)
def add(sig,t0,pan=0.5):
    i=int(t0*sr); j=min(n,i+len(sig)); s=sig[:j-i]
    L[i:j]+=s*(1-pan); R[i:j]+=s*pan
nb=int(total/bar)+1
for b in range(nb):
    ch=prog[b%4]; t0=b*bar; d=bar+0.6; t=np.arange(int(d*sr))/sr
    env=np.minimum(t/1.2,1)*np.minimum((d-t)/1.0,1)
    for k,m in enumerate(ch):
        for det,pan in((-0.004,0.3),(0.004,0.7)):
            fr=f(m)*(1+det)
            sig=(np.sin(2*np.pi*fr*t)+0.25*np.sin(2*np.pi*2*fr*t)+0.08*np.sin(2*np.pi*3*fr*t))*env*0.05
            add(sig,t0,pan)
    # soft plucks: arpeggio on eighth notes, sparse
    notes=[ch[2]+12,ch[3]+12,ch[4]+12,ch[3]+12,ch[2]+12,ch[4]+12,ch[3]+12,ch[1]+12]
    for e,m in enumerate(notes):
        if b<2 or (e%2==1 and b%2==0): continue
        d2=0.9; t2=np.arange(int(d2*sr))/sr; fr=f(m)
        sig=np.sin(2*np.pi*fr*t2)*np.exp(-t2*5.5)*0.07+np.sin(2*np.pi*2*fr*t2)*np.exp(-t2*9)*0.02
        add(sig,t0+e*beat/2,0.35+0.3*((e%4)/3))
    # gentle bass on beat 1 and 3
    for e in (0,2):
        d3=1.2; t3=np.arange(int(d3*sr))/sr; fr=f(ch[0]-12)
        add(np.sin(2*np.pi*fr*t3)*np.exp(-t3*2.2)*0.10,t0+e*beat,0.5)
t=np.arange(n)/sr
fade=np.minimum(t/2.5,1)*np.minimum((total-t)/4.0,1)
st=np.stack([L,R],1)*fade[:,None]; st/=np.max(np.abs(st))*1.12
w=wave.open('bed.wav','wb'); w.setnchannels(2); w.setsampwidth(2); w.setframerate(sr); w.writeframes((st*32767).astype('<i2').tobytes()); w.close()
