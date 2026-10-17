import csv,json,collections,hashlib,glob,os,sys
sys.stdout.reconfigure(encoding="utf-8")
B=r"data/raw/weather/kma_asos_2023_2025/20261016T150911Z"
rows=list(csv.DictReader(open(B+"/asos155_hourly_2023_2025.csv",encoding="utf-8-sig")))
out={"rows":len(rows),"first":rows[0]["tm"],"last":rows[-1]["tm"]}
for f in ["taQcflg","rnQcflg","wsQcflg","hmQcflg"]:
    out[f]=dict(collections.Counter(r[f] for r in rows))
rnv=[float(r["rn"]) for r in rows if r["rn"]!=""]
out["rn_nonblank"]=len(rnv); out["rn_zero"]=sum(1 for v in rnv if v==0)
out["rn_blank_with_flag"]=dict(collections.Counter(r["rnQcflg"] for r in rows if r["rn"]==""))
out["hours_set"]=sorted(set(r["tm"][11:] for r in rows))[:3]
dl=sorted(glob.glob(r"data/raw/approved_public_apis/20261016T150727234763Z/derived_csv/asos155_daily_*.csv"))
D={}
for p in dl:
    for r in csv.DictReader(open(p,encoding="utf-8-sig")): D[r["tm"]]=r
out["daily_cols"]=list(next(iter(D.values())).keys())[:20]
H=collections.defaultdict(list)
for r in rows: H[r["tm"][:10]].append(r)
dt=[];dr=[];dmax=[];n=0
for d,hs in H.items():
    if d not in D: continue
    n+=1; ta=[float(h["ta"]) for h in hs if h["ta"]!=""]
    try:
        if len(ta)==24: dt.append(abs(sum(ta)/24-float(D[d]["avgTa"]))); dmax.append(abs(max(ta)-float(D[d]["maxTa"])))
    except: pass
    rs=sum(float(h["rn"]) for h in hs if h["rn"]!="")
    dv=D[d].get("sumRn","")
    dr.append((rs,float(dv) if dv!="" else None))
def st(a): a=sorted(a); return {"n":len(a),"mean":round(sum(a)/len(a),3),"p95":a[int(.95*len(a))],"max":a[-1]}
out["days_common"]=n; out["avgTa_absdiff"]=st(dt); out["maxTa_absdiff(hourly max vs daily max)"]=st(dmax)
both=[(a,b) for a,b in dr if b is not None]
out["rain_days_daily_nonblank"]=len(both)
out["rain_exact_match(|d|<=0.05)"]=sum(1 for a,b in both if abs(a-b)<=0.05)
out["rain_absdiff"]=st([abs(a-b) for a,b in both])
out["daily_blank_hourly_pos"]=sum(1 for a,b in dr if b is None and a>0)
json.dump(out,open(B+"/../grok_asos_hourly_qc_20261017.json","w",encoding="utf-8"),ensure_ascii=False,indent=1)
print(json.dumps(out,ensure_ascii=False))
for p in sorted(glob.glob(B+"/*")): print(os.path.basename(p),os.path.getsize(p),hashlib.sha256(open(p,"rb").read()).hexdigest())
