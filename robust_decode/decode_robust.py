# SPDX-License-Identifier: Apache-2.0
import sys, json, cv2, numpy as np
sys.path.insert(0, r"D:/Work/Projects/GitHub/Forensic Fingerprinting")
from decode import deskew, line_baseline, subpixel_gaps
meta=json.load(open("meta.json"))
gray0=cv2.imread("received_cropped.jpg",cv2.IMREAD_GRAYSCALE)
k=cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(25,25))
bg=cv2.morphologyEx(gray0,cv2.MORPH_CLOSE,k)
norm=np.clip(gray0.astype(np.float64)/np.maximum(bg,1)*255,0,255).astype(np.uint8)
gray,ang=deskew(norm)
ink=255.0-gray.astype(np.float64)
prof=np.convolve(ink.sum(axis=1),np.ones(3)/3,mode="same")
p=prof-prof.mean()
ac=np.correlate(p,p,mode="full")[len(p)-1:]
pitch=30+int(np.argmax(ac[30:120]))
mind=int(0.6*pitch)
cand=[i for i in range(1,len(prof)-1) if prof[i]>=prof[i-1] and prof[i]>prof[i+1] and prof[i]>prof.mean()]
peaks=[]
for i in sorted(cand,key=lambda x:-prof[x]):
    if all(abs(i-j)>=mind for j in peaks):peaks.append(i)
peaks=sorted(peaks)
# Bands: boundaries at midpoints between consecutive peaks
bnds=[0]+[ (peaks[i]+peaks[i+1])//2 for i in range(len(peaks)-1)]+[gray.shape[0]]
bands=[(bnds[i],bnds[i+1]) for i in range(len(peaks))]
print(f"deskew {ang:+.2f}, {len(bands)} lines found, {meta['n_lines']} expected")
if len(bands)!=meta["n_lines"]:
    print("still mismatch"); sys.exit()
baselines=[line_baseline(gray,a,b) for a,b in bands]
# line-shift (identical to decode.py)
l_ok=l_tot=0
for t in range(meta["n_lines"]//3):
    i=3*t+1
    bp,bm,bn=baselines[i-1],baselines[i],baselines[i+1]
    truth=meta["lines"][i]["line_bit"]
    if None in (bp,bm,bn) or truth is None:continue
    stat=(bm-bp)-(bn-bm); bit=1 if stat>0 else 0
    l_tot+=1; l_ok+=int(bit==truth)
# word-shift (identical to decode.py)
w_ok=w_tot=w_erase=0; votes={}; slot=0; payload=meta["payload"]
for li,(a,b) in enumerate(bands):
    info=meta["lines"][li]; nw=info["n_words"]
    slots=[i for i in range(1,nw-1) if i%2==1]
    widths=subpixel_gaps(gray,a,b,nw)
    if widths is None:
        w_erase+=len(slots); slot+=len(slots); continue
    stats=[(widths[j-1]-widths[j]) for j in slots]
    for widx,raw in zip(slots,stats):
        truth=info["word_bits"][widx]; bit=1 if raw>0 else 0
        if truth is not None:
            w_tot+=1; w_ok+=int(bit==truth)
            pp=slot%len(payload); votes.setdefault(pp,[]).append(bit)
        slot+=1
pay_ok=sum(1 for pp,v in votes.items() if int(np.mean(v)>0.5)==payload[pp])
la=l_ok/l_tot if l_tot else float('nan'); wa=w_ok/w_tot if w_tot else float('nan')
print(f"line-shift : {l_ok}/{l_tot} = {la:.3f} raw bit accuracy")
print(f"word-shift : {w_ok}/{w_tot} = {wa:.3f} raw bit accuracy ({w_erase} erasures)")
print(f"payload    : {pay_ok}/{len(votes)} bits after repetition vote")
go=(wa>=0.85) or (la>=0.90)
print(f"GO/NO-GO   : {'GO' if go else 'NO-GO'} (word>=0.85 or line>=0.90)")
