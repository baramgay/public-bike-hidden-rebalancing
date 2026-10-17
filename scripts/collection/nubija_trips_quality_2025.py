"""원본 보존본: scripts/archive/collection_20261016/. 실행 시에만 로컬 검증한다."""

def main():
    """Exact duplicate, timestamp, missing-day, and 2025 station-code checks.
    Only completed 2025 CSV is read. Temporary SQLite storage is deleted on exit.
    """
    import collections, datetime, json, pathlib, sqlite3, tempfile
    import pandas as pd
    root = pathlib.Path(__file__).resolve().parents[2]
    raw = root / 'data/raw/nubija_trips/nubija_trips_2025.csv'
    meta = root / 'data/metadata/nubija_trips.md'
    stations_path = root / 'data/raw/nubija_stations/nubija_stations_2023_2025.xlsx'
    stations = pd.read_excel(stations_path, sheet_name='2025년', dtype={'터미널번호': str})
    station_codes = set(stations['터미널번호'].dropna().str.strip())
    counts = collections.Counter(); day_counts = collections.Counter(); unknown = {'출발터미널': collections.Counter(), '도착터미널': collections.Counter()}; special = {'출발터미널': collections.Counter(), '도착터미널': collections.Counter()}
    examples = {}; min_duration = None; max_duration = None; rows = 0
    with tempfile.TemporaryDirectory(prefix='nubija_duplicate_check_') as tmp:
        con = sqlite3.connect(str(pathlib.Path(tmp) / 'trip_rows.sqlite'))
        con.execute('PRAGMA journal_mode=OFF'); con.execute('PRAGMA synchronous=OFF'); con.execute('PRAGMA temp_store=FILE'); con.execute('PRAGMA cache_size=-32768')
        con.execute('CREATE TABLE trips (c0 TEXT,c1 TEXT,c2 TEXT,c3 TEXT,c4 TEXT,c5 TEXT,c6 TEXT)')
        for chunk in pd.read_csv(raw, encoding='cp949', dtype=str, keep_default_na=False, chunksize=100000):
            rows += len(chunk)
            con.executemany('INSERT INTO trips VALUES (?,?,?,?,?,?,?)', chunk.itertuples(index=False, name=None)); con.commit()
            start = pd.to_datetime(chunk['출발일'] + ' ' + chunk['출발시간'], format='%Y-%m-%d %H:%M:%S', errors='coerce')
            end = pd.to_datetime(chunk['도착일'] + ' ' + chunk['도착시간'], format='%Y-%m-%d %H:%M:%S', errors='coerce')
            counts['invalid_start_datetime'] += int(start.isna().sum()); counts['invalid_end_datetime'] += int(end.isna().sum())
            seconds = (end - start).dt.total_seconds(); valid = seconds.dropna()
            if len(valid):
                lo = float(valid.min()); hi = float(valid.max()); min_duration = lo if min_duration is None else min(lo, min_duration); max_duration = hi if max_duration is None else max(hi, max_duration)
            conditions = {'negative_duration': seconds.lt(0), 'zero_duration': seconds.eq(0), 'positive_to_5min': seconds.gt(0) & seconds.le(300), 'over_5_to_15min': seconds.gt(300) & seconds.le(900), 'over_15_to_30min': seconds.gt(900) & seconds.le(1800), 'over_30_to_60min': seconds.gt(1800) & seconds.le(3600), 'over_1_to_2h': seconds.gt(3600) & seconds.le(7200), 'over_2_to_24h': seconds.gt(7200) & seconds.le(86400), 'over_24h_to_7d': seconds.gt(86400) & seconds.le(604800), 'over_7d_to_30d': seconds.gt(604800) & seconds.le(2592000), 'over_30d': seconds.gt(2592000), 'end_calendar_date_before_start': chunk['도착일'].lt(chunk['출발일'])}
            for name, condition in conditions.items():
                counts[name] += int(condition.sum())
                if name in ['negative_duration', 'over_30d'] and name not in examples and condition.any():
                    examples[name] = chunk.loc[condition].head(3).values.tolist()
            day_counts.update(chunk['출발일'].value_counts().to_dict())
            for c in unknown:
                unknown[c].update(chunk.loc[~chunk[c].isin(station_codes), c].value_counts().to_dict())
                mask = chunk[c].str.strip().isin(['', '0', '-1', 'NULL', 'null', 'NaN', 'nan', '알수없음', '알 수 없음', '미상']) | ~chunk[c].str.fullmatch(r'\d+')
                special[c].update(chunk.loc[mask, c].value_counts().to_dict())
        print('TIMESTAMP_SCAN_DONE', rows, flush=True)
        duplicate_groups = 0; duplicate_excess_rows = 0; rows_in_duplicate_groups = 0; duplicate_examples = []
        for row in con.execute('SELECT c0,c1,c2,c3,c4,c5,c6,COUNT(*) AS n FROM trips GROUP BY c0,c1,c2,c3,c4,c5,c6 HAVING COUNT(*)>1'):
            duplicate_groups += 1; duplicate_excess_rows += row[-1] - 1; rows_in_duplicate_groups += row[-1]
            if len(duplicate_examples) < 3: duplicate_examples.append(row)
        con.close()
    missing_days = [str(d.date()) for d in pd.date_range('2025-01-01', '2025-12-31') if str(d.date()) not in day_counts]
    result = {'records': rows, 'station_reference': str(stations_path), 'station_sheet': '2025년', 'station_rows': len(stations), 'station_unique_codes': len(station_codes), 'datetime_format': '%Y-%m-%d %H:%M:%S', 'duration_seconds_min': min_duration, 'duration_seconds_max': max_duration, 'counts': dict(counts), 'missing_departure_dates': missing_days, 'unknown_station_codes_and_counts': {c: dict(v) for c,v in unknown.items()}, 'special_or_nonnumeric_codes_and_counts': {c: dict(v) for c,v in special.items()}, 'duplicate_definition': 'Exact equality of all seven parsed original text fields; SQLite full-key GROUP BY, no probabilistic hashes', 'duplicate_groups': duplicate_groups, 'duplicate_excess_rows': duplicate_excess_rows, 'rows_in_duplicate_groups': rows_in_duplicate_groups, 'duplicate_examples': duplicate_examples, 'anomaly_examples': examples, 'checked_utc': datetime.datetime.now(datetime.timezone.utc).isoformat()}
    with meta.open('a', encoding='utf-8') as f:
        f.write('\n## 2025년 심화 품질 검증\n\n원본은 변경하지 않았다. 월 누락을 보간하지 않았으며 원인 미확정이다. 관측이 없는 7월은 수요 0으로 처리하지 않고 모델 학습·성능평가에서 제외할 필요가 있다. 대여시간 구간은 상호 배타적(음수·0·각 양수 구간)이며 날짜역전은 별도 중첩 집계다.\n\n```json\n' + json.dumps(result, ensure_ascii=False, indent=2) + '\n```\n')
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
