"""원본 보존본: scripts/archive/collection_20261016/. 실행 시에만 로컬 검증한다."""

def main():
    """기존 원자료를 읽어 수집 당시 실행한 품질검사와 해시를 재현한다."""
    import pathlib
    import pandas as pd
    import openpyxl
    import hashlib
    import datetime
    
    root = pathlib.Path(__file__).resolve().parents[2] / "data/raw"
    w = openpyxl.load_workbook(root / "nubija_stations/nubija_stations_2023_2025.xlsx", read_only=True, data_only=True)
    sets = []
    for s in w:
        rows = list(s.values)
        d = pd.DataFrame(rows[1:], columns=rows[0])
        sets.append(set(d["터미널번호"]))
        print(s.title, "rows", len(d), "id dup", d["터미널번호"].duplicated().sum(), "null", d.isna().sum().to_dict(), "status", d["사용유무"].value_counts(dropna=False).to_dict(), "coord range", d["위도"].min(), d["위도"].max(), d["경도"].min(), d["경도"].max())
    print("id overlap", len(sets[0] & sets[1]), len(sets[1] & sets[2]), len(set.union(*sets)))
    for f in list((root / "transit").glob("*.csv")) + list((root / "spatial").glob("*.csv")):
        for enc in ["utf-8-sig", "cp949"]:
            try:
                d = pd.read_csv(f, encoding=enc)
                break
            except UnicodeDecodeError:
                continue
        print(f.name, "encoding", enc, "shape", d.shape, "cols", list(d.columns), "null", d.isna().sum().to_dict())
        print(d.head(2).to_dict("records"))
    for folder in ["nubija_stations", "operations", "transit", "spatial"]:
        for p in sorted((root / folder).glob("*")):
            if p.is_file():
                print(p.relative_to(root).as_posix(), datetime.datetime.fromtimestamp(p.stat().st_mtime, datetime.timezone(datetime.timedelta(hours=9))).isoformat(), p.stat().st_size, hashlib.sha256(p.read_bytes()).hexdigest())


if __name__ == "__main__":
    main()
