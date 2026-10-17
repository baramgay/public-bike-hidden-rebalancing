"""grok_followup_04: 상가(상권)정보 2024-12 경남 → 창원5구 식료품 소매 후보 추출 (현재시점 보완후보, 2025 시설 아님)."""
import pandas as pd,sys,json,hashlib,os
sys.stdout.reconfigure(encoding="utf-8")
R="data/raw/grok_followup_04/20261017/"; O="data/processed/grok_followup_04/20261017/"
df=pd.read_csv(R+"sbiz_gyeongnam_202412.csv",dtype=str,encoding="utf-8")
print("경남 G204 소분류:",df[df["상권업종중분류코드"]=="G204"]["상권업종소분류코드"].value_counts().to_dict())
cw=df[df["시군구명"].fillna("").str.startswith("창원")].copy()
TIER={"G20404":"A_슈퍼마켓","G20405":"B_편의점",
 "G20503":"C_식료품전문(정육)","G20504":"C_식료품전문(건어물젓갈)","G20505":"C_식료품전문(수산물)","G20506":"C_식료품전문(채소과일)","G20509":"C_식료품전문(반찬식료품)","G20501":"C_식료품전문(곡물)"}
EXCL={"G20502":"가축사료","G20507":"아이스크림할인점","G20508":"건강보조식품","G20499":"그외기타종합소매(내용불명)"}
f=cw[cw["상권업종소분류코드"].isin(TIER)].copy(); f["grok_tier"]=f["상권업종소분류코드"].map(TIER)
x=pd.to_numeric(f["경도"],errors="coerce"); y=pd.to_numeric(f["위도"],errors="coerce")
f["coord_missing"]=x.isna()|y.isna()
f["coord_out_of_bbox"]=~f["coord_missing"]&~(x.between(128.35,128.85)&y.between(35.0,35.42))
f.to_csv(O+"grok_sbiz_changwon5_food_retail_202412.csv",index=False,encoding="utf-8-sig")
s={"source_rows_gyeongnam":len(df),"changwon_rows":len(cw),"extracted":len(f),
 "by_tier":f["grok_tier"].value_counts().to_dict(),
 "by_gu_tier":f.groupby(["시군구명","grok_tier"]).size().unstack(fill_value=0).to_dict(orient="index"),
 "coord_missing":int(f["coord_missing"].sum()),"coord_out_of_bbox(128.35-128.85E,35.0-35.42N)":int(f["coord_out_of_bbox"].sum()),
 "dup_store_id":int(f["상가업소번호"].duplicated().sum()),
 "dup_name_addr":int(f.duplicated(["상호명","도로명주소"]).sum()),
 "excluded_codes":EXCL,"excluded_counts":cw[cw["상권업종소분류코드"].isin(EXCL)]["상권업종소분류코드"].value_counts().to_dict()}
json.dump(s,open(O+"grok_sbiz_changwon5_food_retail_202412_qc.json","w",encoding="utf-8"),ensure_ascii=False,indent=1)
print(json.dumps(s,ensure_ascii=False))
for p in [O+"grok_sbiz_changwon5_food_retail_202412.csv"]: print(os.path.getsize(p),hashlib.sha256(open(p,"rb").read()).hexdigest())
