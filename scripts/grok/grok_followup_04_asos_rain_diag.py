"""grok_followup_04 ASOS 강수 진단 (읽기 전용). 시간이동·보정 없음.
공식 근거: KMA 국가기후데이터센터 ASOS 자료설명(강수량 겨울철 11~3월 3시간 간격 제공; QC 0정상/1오류/9결측),
data.go.kr 15057210 활용가이드(플래그 정상=null,오류=1,결측=9; rn 단위 mm)."""
import csv,glob,collections,sys,json
sys.stdout.reconfigure(encoding="utf-8")
H=list(csv.DictReader(open("data/raw/weather/kma_asos_2023_2025/20261016T150911Z/asos155_hourly_2023_2025.csv",encoding="utf-8-sig")))
D={}
for p in sorted(glob.glob("data/raw/approved_public_apis/20261016T150727234763Z/derived_csv/asos155_daily_*.csv")):
    for r in csv.DictReader(open(p,encoding="utf-8-sig")): D[r["tm"]]=r
g=collections.defaultdict(list)
for r in H: g[r["tm"][:10]].append(r)
rows=[]
for d in sorted(g):
    hs=g[d]; m=int(d[5:7]); winter=m in (11,12,1,2,3)
    vals=[float(h["rn"]) for h in hs if h["rn"]!=""]
    f9=sum(1 for h in hs if h["rnQcflg"]=="9"); f1=sum(1 for h in hs if h["rnQcflg"]=="1")
    nz=sorted(set(int(h["tm"][11:13]) for h in hs if h["rn"]!=""))
    s=round(sum(vals),1) if vals else None
    dv=D.get(d,{}).get("sumRn","")
    dvf=float(dv) if dv!="" else None
    if dvf is None and not vals: cls="양쪽빈값"
    elif dvf is None: cls="일빈값_시간값있음"
    elif not vals: cls="일값있음_시간전부빈값"
    else: cls="일치" if abs(s-dvf)<=0.05 else "불일치"
    comparable = (dvf is not None) and (f9==0) and (f1==0)
    rows.append(dict(date=d,season="동절기(11-3)" if winter else "하절기(4-10)",daily_sumRn=dv,hourly_sum=("" if s is None else s),
        diff=("" if (s is None or dvf is None) else round(s-dvf,1)),hourly_rn_nonblank=len(vals),rn_hours=" ".join(map(str,nz)),
        rnQcflg9_hours=f9,rnQcflg1_hours=f1,quality_comparable=comparable,class_existing_rule=cls))
O="data/processed/grok_followup_04/20261017/grok_asos_rain_daily_vs_hourly_diag.csv"
w=csv.DictWriter(open(O,"w",newline="",encoding="utf-8-sig"),fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
summ={}
for key in ["전체","동절기(11-3)","하절기(4-10)"]:
    sub=[r for r in rows if key=="전체" or r["season"]==key]
    withd=[r for r in sub if r["daily_sumRn"]!=""]
    comp=[r for r in withd if r["quality_comparable"] and r["hourly_sum"]!=""]
    c=collections.Counter(r["class_existing_rule"] for r in sub)
    md=[abs(r["diff"]) for r in comp if r["diff"]!=""]
    summ[key]={"days":len(sub),"daily_sumRn_nonblank":len(withd),"classes":dict(c),
      "quality_comparable(no flag9/1, both values)":len(comp),"match_in_comparable":sum(1 for r in comp if r["class_existing_rule"]=="일치"),
      "mismatch_in_comparable":sum(1 for r in comp if r["class_existing_rule"]=="불일치"),"max_absdiff_comparable":max(md) if md else None}
# winter: hours present pattern
wh=collections.Counter(int(r["tm"][11:13]) for r in H if r["rn"]!="" and int(r["tm"][5:7]) in (11,12,1,2,3))
summ["winter_rn_nonblank_by_hour"]=dict(sorted(wh.items()))
json.dump(summ,open(O.replace(".csv","_summary.json"),"w",encoding="utf-8"),ensure_ascii=False,indent=1)
print(json.dumps(summ,ensure_ascii=False))
