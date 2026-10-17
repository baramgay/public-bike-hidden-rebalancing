import zipfile,sys,json,hashlib,os,pandas as pd
sys.stdout.reconfigure(encoding="utf-8")
R="data/raw/accessibility_facilities"; O=R+"/grok_hira_changwon5_20261017"; os.makedirs(O,exist_ok=True)
res={}
for tag in ["2025-12","2024-12"]:
    zp=f"{R}/hira_hospital_pharmacy_{tag}_raw.zip"; z=zipfile.ZipFile(zp)
    info={"size":os.path.getsize(zp),"sha256":hashlib.sha256(open(zp,"rb").read()).hexdigest(),
          "entries":[[i.filename,i.file_size,format(i.CRC,"08X")] for i in z.infolist()]}
    pick={}
    for i in z.namelist():
        b=os.path.basename(i)
        if b.startswith("1."): pick["hosp"]=i
        if b.startswith("2."): pick["pharm"]=i
        if b.startswith("5."): pick["dept"]=i
    out={}
    for k in ["hosp","pharm"]:
        df=pd.read_excel(z.open(pick[k]),dtype=str)
        cw=df[df["시군구코드명"].fillna("").str.startswith("창원")]
        cw.to_csv(f"{O}/hira_{k}_changwon5_{tag}.csv",index=False,encoding="utf-8-sig")
        x=pd.to_numeric(cw["좌표(X)"],errors="coerce"); y=pd.to_numeric(cw["좌표(Y)"],errors="coerce")
        out[k]={"nation_rows":len(df),"changwon_rows":len(cw),"by_gu":cw["시군구코드명"].value_counts().to_dict(),
          "types":cw["종별코드명"].value_counts().to_dict(),"coord_missing":int((x.isna()|y.isna()).sum()),
          "coord_range":[float(x.min()),float(x.max()),float(y.min()),float(y.max())],
          "addr_missing":int(cw["주소"].isna().sum()),"id_dup":int(cw["암호화요양기호"].duplicated().sum()),
          "addr_gu_mismatch":int(sum(1 for a,g in zip(cw["주소"].fillna(""),cw["시군구코드명"]) if g.replace("창원","") not in a))}
        if k=="hosp": ids=set(cw["암호화요양기호"])
    d=pd.read_excel(z.open(pick["dept"]),dtype=str); dc=d[d["암호화요양기호"].isin(ids)]
    dc.to_csv(f"{O}/hira_dept_changwon5_{tag}.csv",index=False,encoding="utf-8-sig")
    out["dept"]={"cols":list(d.columns),"changwon_rows":len(dc),"inst_with_dept":dc["암호화요양기호"].nunique(),"hosp_without_dept":len(ids-set(dc["암호화요양기호"]))}
    info["extract"]=out; res[tag]=info
for f in sorted(os.listdir(O)): res.setdefault("outputs",[]).append([f,os.path.getsize(O+"/"+f),hashlib.sha256(open(O+"/"+f,"rb").read()).hexdigest()])
json.dump(res,open(O+"/grok_hira_extract_qc.json","w",encoding="utf-8"),ensure_ascii=False,indent=1)
print(json.dumps(res,ensure_ascii=False))
