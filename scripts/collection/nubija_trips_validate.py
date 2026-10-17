"""확보 완료된 2023~2025 CSV만 검증한다. 2022 다운로드·파일 대기 없음."""

def main():
    """Faithful copy of the running streaming CSV validation process.
    Reads only completed originals; does not alter raw files or extract ZIP to disk.
    """
    import pathlib, json, datetime
    import pandas as pd
    raw = pathlib.Path(__file__).resolve().parents[2] / 'data/raw/nubija_trips'
    meta = raw.parents[1] / 'metadata' / 'nubija_trips.md'
    def scan(handle, label):
        first = handle.read(8192); handle.seek(0); enc = 'utf-8-sig'
        try:
            first.decode(enc)
        except UnicodeDecodeError:
            enc = 'cp949'; first.decode(enc)
        cols = None; n = 0; missing = {}; ranges = {}; samples = []; months = {}; terminals = {}
        for chunk in pd.read_csv(handle, encoding=enc, dtype=str, keep_default_na=False, chunksize=100000):
            if cols is None:
                cols = list(chunk.columns)
                if cols != ['자전거번호','출발터미널','출발일','출발시간','도착터미널','도착일','도착시간']:
                    raise ValueError(f'필수 스키마 불일치: {label}')
                missing = {c: 0 for c in cols}; samples = chunk.head(3).values.tolist()
            n += len(chunk)
            for c in cols:
                s = chunk[c]; missing[c] += int(s.str.strip().eq('').sum())
                if c in ['출발일', '도착일']:
                    valid = s[s.str.strip().ne('')]
                    if len(valid):
                        mn = valid.min(); mx = valid.max(); prev = ranges.get(c, [mn, mx])
                        ranges[c] = [min(prev[0], mn), max(prev[1], mx)]
                        counts = valid.str[:7].value_counts(); d = months.setdefault(c, {})
                        for k, v in counts.items():
                            d[k] = d.get(k, 0) + int(v)
                if '터미널' in c:
                    terminals.setdefault(c, set()).update(s)
        if n == 0:
            raise ValueError(f'자료행 없음: {label}')
        result = {'entry': label, 'encoding': enc, 'records': n, 'columns': cols, 'missing_blank_cells': missing,
                  'date_ranges_raw_strings': ranges, 'monthly_counts': months,
                  'unique_terminal_counts': {c: len(v) for c, v in terminals.items()}, 'first_3_records': samples,
                  'checked_utc': datetime.datetime.now(datetime.timezone.utc).isoformat()}
        with meta.open('a', encoding='utf-8') as f:
            f.write('\n### 전체 CSV 검증: ' + label + '\n\n```json\n' + json.dumps(result, ensure_ascii=False, indent=2) + '\n```\n')
        print('VALIDATED', json.dumps(result, ensure_ascii=False), flush=True)
    paths = [raw / f'nubija_trips_{year}.csv' for year in (2025, 2024, 2023)]
    for path in paths:
        if not path.is_file():
            raise FileNotFoundError(f'완료 원본 없음(자동 대기·재시도 없음): {path.name}')
    for path in paths:
        with path.open('rb') as handle:
            scan(handle, path.name)
    print('AVAILABLE_CSV_VALIDATION_COMPLETE', flush=True)


if __name__ == "__main__":
    main()
