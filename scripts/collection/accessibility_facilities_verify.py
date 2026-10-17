"""원본 보존본: scripts/archive/collection_20261016/. 실행 시에만 로컬 검증한다."""

def main():
    import csv, json, pathlib, hashlib, sys
    from collections import Counter
    from datetime import datetime,timezone
    root=pathlib.Path(__file__).resolve().parents[2] / 'data/raw/accessibility_facilities'
    processed=root.parents[1]/'processed/accessibility_facilities'
    processed.mkdir(parents=True,exist_ok=True)
    output=[]
    for p in root.glob('*.csv'):
        if p.name.endswith('_subset.csv'): continue
        raw=p.read_bytes()
        enc=None
        for candidate in ['utf-8-sig','cp949']:
            try: text=raw.decode(candidate);enc=candidate;break
            except UnicodeDecodeError: pass
        if enc is None: raise ValueError(str(p)+' encoding failed')
        rows=list(csv.DictReader(text.splitlines()))
        cols=list(rows[0]) if rows else []
        selected=[r for r in rows if any('창원시' in str(v) for v in r.values())] if p.name.startswith('nationwide_') else rows
        item={'file':p.name,'encoding':enc,'rows':len(rows),'changwon_rows':len(selected),'columns':cols,'missing_changwon':{k:sum(not str(r.get(k,'')).strip() for r in selected) for k in cols},'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),'stored_utc':datetime.fromtimestamp(p.stat().st_mtime,timezone.utc).isoformat()}
        if '의료기관종별' in cols:item['medical_types']=dict(Counter(r['의료기관종별'] for r in selected))
        if '취급품목' in cols:
            item['reference_dates']=sorted(set(r.get('데이터기준일자','') for r in selected))
            item['market_types']=dict(Counter(r['시장유형'] for r in selected))
            item['food_item_candidates']=sum(any(x in r['취급품목'] for x in ['농산물','축산물','수산물','가공식품']) for r in selected)
            item['missing_coordinate_names']=[r['시장명'] for r in selected if not r['위도'].strip() or not r['경도'].strip()]
            valid=[r for r in selected if r['위도'].strip() and r['경도'].strip()]
            item['invalid_coordinate_range']=sum(not(34<=float(r['위도'])<=36 and 127<=float(r['경도'])<=130) for r in valid)
            dest=processed/'changwon_traditional_markets_20251110_subset.csv'
            with dest.open('w',encoding='utf-8-sig',newline='') as f:
                w=csv.DictWriter(f,fieldnames=cols);w.writeheader();w.writerows(selected)
        output.append(item)
    (processed/'verification.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(output,ensure_ascii=False))


if __name__ == "__main__":
    main()
