"""자전거 번호 연쇄로 '이용 기록 없이 옮겨진 자전거'(재배치·정비 추정)를 찾는다.

같은 자전거의 반납 거점과 다음 대여 거점이 다르면, 그 사이 사람 이용 기록 없이 자전거가
이동한 것이다. 재배치 차량·정비 수거·기록 누락이 섞여 있으므로 '무인 이동'으로 부르고
간격·속도·묶음 여부·운영센터 관련 여부로 나눈다.

입력
- data/raw/nubija_trips/nubija_trips_{2023,2024,2025}.csv : 헤더만 한글(CP949), 데이터 행은 ASCII.
  duckdb의 CP949 디코더는 버퍼 경계에서 정상 행을 깨뜨리므로 헤더를 건너뛰고 기본 인코딩으로 읽는다.
- data/raw/nubija_stations/nubija_stations_2023_2025.xlsx : 연도별 터미널 좌표.
- data/raw/elevation/Copernicus_DSM_COG_10_N35_00_E128_00_DEM.tif : 표면고도(30m).
출력: data/processed/bike_chains/
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import rasterio

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "processed" / "bike_chains"
YEARS = (2023, 2024, 2025)
EXPECTED_ROWS = {2023: 4_066_540, 2024: 4_582_332, 2025: 4_419_063}
# 출발 기록이 통째로 없는 기간. 이 구간에 걸친 쌍은 판정할 수 없다.
UNOBSERVED = [("2025-07-01 00:00:00", "2025-08-01 00:00:00")]
# 운영일 경계: 01~04시 대여가 거의 없어 04시를 하루의 시작으로 둔다.
DAY_START_HOUR = 4
OPS_CENTERS = {243: "누비자운영센터", 327: "누비자중앙센터"}
# 반납~다음 대여 사이 직선 이동속도가 이보다 빠르면 차량 이동으로 보기 어렵다(기록 오류 후보).
MAX_PLAUSIBLE_KMH = 60.0
MIN_PLAUSIBLE_GAP_S = 5 * 60


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def load_stations() -> pd.DataFrame:
    sheets = pd.read_excel(RAW / "nubija_stations" / "nubija_stations_2023_2025.xlsx", sheet_name=None)
    rows = []
    for name, df in sheets.items():
        year = int(name[:4])
        part = df.rename(columns={"터미널번호": "station_id", "터미널명": "name", "구": "district", "동": "dong",
                                  "위도": "lat", "경도": "lon", "사용유무": "in_use"})
        part["year"] = year
        rows.append(part[["year", "station_id", "name", "district", "dong", "lat", "lon", "in_use"]])
    st = pd.concat(rows, ignore_index=True)
    st["in_use"] = st["in_use"].eq("사용함")
    # 좌표는 가장 최근 연도 기준. 2023→2024 좌표가 바뀐 6곳은 이동 거리를 따로 기록한다.
    latest = st.sort_values("year").groupby("station_id").tail(1).set_index("station_id")
    first = st.sort_values("year").groupby("station_id").head(1).set_index("station_id").reindex(latest.index)
    latest["coord_shift_m"] = haversine_km(first["lat"], first["lon"], latest["lat"], latest["lon"]) * 1000
    latest["years_listed"] = st.groupby("station_id")["year"].apply(lambda s: ",".join(map(str, sorted(s))))
    latest["years_in_use"] = st[st["in_use"]].groupby("station_id")["year"].apply(lambda s: ",".join(map(str, sorted(s))))
    latest["is_ops_center"] = latest.index.isin(OPS_CENTERS)
    return latest.reset_index()


def haversine_km(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = (np.radians(np.asarray(v, dtype=float)) for v in (lat1, lon1, lat2, lon2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 6371.0088 * 2 * np.arcsin(np.sqrt(a))


def ground_elevation(stations: pd.DataFrame) -> pd.Series:
    """표면고도(DSM)는 건물·수목 높이를 포함하므로 3x3 격자(약 90m) 최솟값을 지면 근사로 쓴다."""
    dem_path = RAW / "elevation" / "Copernicus_DSM_COG_10_N35_00_E128_00_DEM.tif"
    with rasterio.open(dem_path) as r:
        band = r.read(1)
        out = []
        for lon, lat in zip(stations["lon"], stations["lat"]):
            row, col = r.index(lon, lat)
            win = band[max(row - 1, 0):row + 2, max(col - 1, 0):col + 2]
            out.append(float(np.min(win)))
    return pd.Series(out, index=stations.index)


def main() -> int:
    t_start = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    tmp = ROOT / ".tmp"
    tmp.mkdir(exist_ok=True)
    con = duckdb.connect()
    con.execute(f"SET temp_directory='{tmp.as_posix()}'")
    con.execute("SET preserve_insertion_order=false")

    audit: dict = {"inputs": {}, "rows": {}, "definitions": {}}

    # --- A. 원본 → 정제 이용 기록 -------------------------------------------------
    parts = []
    for y in YEARS:
        path = RAW / "nubija_trips" / f"nubija_trips_{y}.csv"
        audit["inputs"][path.name] = {"bytes": path.stat().st_size, "sha256": sha256(path)}
        parts.append(f"""
            select {y} as src_year, bike, o, dep_d, dep_t, d, ret_d, ret_t
            from read_csv('{path.as_posix()}', header=false, skip=1, delim=',', quote='',
                 columns={{'bike':'VARCHAR','o':'VARCHAR','dep_d':'VARCHAR','dep_t':'VARCHAR',
                          'd':'VARCHAR','ret_d':'VARCHAR','ret_t':'VARCHAR'}})""")
    con.execute("create table raw as " + " union all ".join(parts))
    raw_counts = dict(con.execute("select src_year, count(*) from raw group by 1").fetchall())
    for y in YEARS:
        if raw_counts.get(y) != EXPECTED_ROWS[y]:
            raise SystemExit(f"{y} 원본 행수 불일치: {raw_counts.get(y)} != {EXPECTED_ROWS[y]}")
    audit["rows"]["raw"] = {str(k): int(v) for k, v in raw_counts.items()}

    con.execute("""
        create table trips as
        select src_year, try_cast(bike as integer) bike, try_cast(o as integer) o, try_cast(d as integer) d,
               try_strptime(dep_d || ' ' || dep_t, '%Y-%m-%d %H:%M:%S') ts,
               try_strptime(ret_d || ' ' || ret_t, '%Y-%m-%d %H:%M:%S') te
        from raw""")
    con.execute("drop table raw")
    bad = con.execute("""select src_year, count(*) from trips
                         where bike is null or o is null or d is null or ts is null or te is null or te < ts
                         group by 1""").fetchall()
    audit["rows"]["excluded_unparseable_or_negative"] = {str(k): int(v) for k, v in bad}
    con.execute("delete from trips where bike is null or o is null or d is null or ts is null or te is null or te < ts")
    audit["rows"]["valid"] = {str(k): int(v) for k, v in
                              con.execute("select src_year, count(*) from trips group by 1 order by 1").fetchall()}

    # --- B. 같은 자전거의 연속 이용 쌍 -------------------------------------------
    unobs = " or ".join(f"(t0 < timestamp '{b}' and t1 > timestamp '{a}')" for a, b in UNOBSERVED)
    con.execute(f"""
        create table pairs as
        with seq as (
            select bike, src_year, o, d, ts, te,
                   lead(o)  over w as next_o,
                   lead(ts) over w as next_ts,
                   lead(src_year) over w as next_year
            from trips
            window w as (partition by bike order by ts, te, o, d)
        )
        select bike, src_year, d as from_station, te as t0, next_o as to_station, next_ts as t1, next_year,
               epoch(next_ts - te) as gap_s
        from seq where next_ts is not null""")
    con.execute(f"""
        alter table pairs add column unobservable boolean;
        update pairs set unobservable = ({unobs});""")

    stations = load_stations()
    stations["elev_m"] = ground_elevation(stations)
    stations.to_csv(OUT / "stations.csv", index=False, encoding="utf-8-sig")
    con.register("st_df", stations[["station_id", "lat", "lon", "district", "elev_m", "is_ops_center"]])
    con.execute("create table st as select * from st_df")

    con.execute("""
        create table pairs2 as
        select p.*,
               case when p.from_station = p.to_station then 'same' else 'moved' end as kind,
               a.district as from_district, b.district as to_district,
               a.elev_m as from_elev, b.elev_m as to_elev,
               2 * 6371.0088 * asin(sqrt(pow(sin(radians(b.lat - a.lat) / 2), 2)
                   + cos(radians(a.lat)) * cos(radians(b.lat)) * pow(sin(radians(b.lon - a.lon) / 2), 2))) as dist_km,
               coalesce(a.is_ops_center, false) or coalesce(b.is_ops_center, false) as touches_ops_center,
               a.station_id is null or b.station_id is null as unmatched_station
        from pairs p
        left join st a on a.station_id = p.from_station
        left join st b on b.station_id = p.to_station""")
    con.execute("drop table pairs")

    # 분류: 겹침(기록 오류) / 판정불가(결측기간) / 제자리 대기 / 무인 이동(세부)
    con.execute(f"""
        create table pc as
        select *,
          case
            when gap_s < 0 then 'overlap_error'
            when unobservable then 'unobservable_gap'
            when kind = 'same' then 'stayed'
            when unmatched_station then 'moved_unmatched_station'
            when touches_ops_center then 'moved_ops_center'
            when gap_s < {MIN_PLAUSIBLE_GAP_S} or (dist_km / greatest(gap_s, 1) * 3600) > {MAX_PLAUSIBLE_KMH}
                 then 'moved_implausible_fast'
            when gap_s > 3 * 86400 then 'moved_after_long_idle'
            else 'moved_plausible'
          end as cls
        from (select *, cast(t1 - interval {DAY_START_HOUR} hour as date) as service_date from pairs2)""")
    con.execute("drop table pairs2")

    # 묶음 이동: 같은 출발·도착 거점 쌍에서 [t0, t1] 창이 다른 자전거와 겹치면 한 차량에 함께 실렸을 수 있다.
    con.execute("""
        create table batch as
        select bike, t0, from_station, to_station,
               (t0 <= max(t1) over (partition by from_station, to_station order by t0, t1, bike
                                    rows between unbounded preceding and 1 preceding))
               or (t1 >= min(t0) over (partition by from_station, to_station order by t0, t1, bike
                                       rows between 1 following and unbounded following)) as in_pair_batch,
               (t0 <= max(t1) over (partition by from_station order by t0, t1, bike
                                    rows between unbounded preceding and 1 preceding))
               or (t1 >= min(t0) over (partition by from_station order by t0, t1, bike
                                       rows between 1 following and unbounded following)) as in_origin_batch
        from pc where cls in ('moved_plausible', 'moved_after_long_idle')""")
    con.execute("""
        create table pairs_final as
        select pc.*, coalesce(b.in_pair_batch, false) in_pair_batch, coalesce(b.in_origin_batch, false) in_origin_batch
        from pc left join batch b using (bike, t0, from_station, to_station)""")
    con.execute("drop table pc; drop table batch")

    n_pairs = con.execute("select count(*) from pairs_final").fetchone()[0]
    n_valid = sum(audit["rows"]["valid"].values())
    n_bikes = con.execute("select count(distinct bike) from trips").fetchone()[0]
    # 보존: 자전거마다 마지막 이용은 다음 쌍이 없으므로 쌍 수 = 유효 이용 수 - 자전거 수
    if n_pairs != n_valid - n_bikes:
        raise SystemExit(f"쌍 보존 실패: {n_pairs} != {n_valid} - {n_bikes}")
    audit["rows"]["pairs"] = int(n_pairs)
    audit["rows"]["bikes"] = int(n_bikes)

    con.execute(f"copy trips to '{(OUT / 'trips_valid.parquet').as_posix()}' (format parquet)")
    con.execute(f"copy pairs_final to '{(OUT / 'pairs.parquet').as_posix()}' (format parquet)")

    # --- 요약 ------------------------------------------------------------------
    def q(sql: str) -> pd.DataFrame:
        return con.execute(sql).df()

    by_year_cls = q("""select year(t1) as year, cls, count(*) n from pairs_final group by all order by 1, 2""")
    by_year_cls.to_csv(OUT / "pairs_by_year_class.csv", index=False, encoding="utf-8-sig")

    moved_set = "('moved_plausible','moved_after_long_idle','moved_ops_center','moved_implausible_fast','moved_unmatched_station')"
    core_set = "('moved_plausible','moved_after_long_idle')"
    yearly = q(f"""
        select year(t1) as year,
               count(*) filter (where cls not in ('overlap_error','unobservable_gap')) as judged_pairs,
               count(*) filter (where cls = 'stayed') as stayed,
               count(*) filter (where cls in {moved_set}) as moved_any,
               count(*) filter (where cls in {core_set}) as moved_core,
               count(*) filter (where cls = 'moved_plausible') as moved_plausible,
               count(*) filter (where cls = 'moved_after_long_idle') as moved_long_idle,
               count(*) filter (where cls = 'moved_ops_center') as moved_ops_center,
               count(*) filter (where cls = 'moved_implausible_fast') as moved_implausible_fast,
               count(*) filter (where cls = 'moved_unmatched_station') as moved_unmatched,
               count(*) filter (where cls = 'unobservable_gap') as unobservable,
               count(*) filter (where cls = 'overlap_error') as overlap_error,
               count(distinct service_date) filter (where cls in {core_set}) as days_with_moves,
               median(gap_s / 3600.0) filter (where cls = 'moved_plausible') as median_gap_h,
               sum(dist_km) filter (where cls in {core_set}) as bike_km_core,
               median(dist_km) filter (where cls in {core_set}) as median_km_core,
               avg(case when in_pair_batch then 1.0 else 0.0 end) filter (where cls in {core_set}) as share_pair_batch,
               avg(case when in_origin_batch then 1.0 else 0.0 end) filter (where cls in {core_set}) as share_origin_batch
        from pairs_final group by 1 order by 1""")
    yearly["moved_core_share_of_judged"] = yearly["moved_core"] / yearly["judged_pairs"]
    yearly["moved_any_share_of_judged"] = yearly["moved_any"] / yearly["judged_pairs"]
    yearly.to_csv(OUT / "yearly_summary.csv", index=False, encoding="utf-8-sig")

    gap_bins = q(f"""
        select year(t1) as year,
               case when gap_s < 3600 then '1) 1시간 미만' when gap_s < 6*3600 then '2) 1~6시간'
                    when gap_s < 12*3600 then '3) 6~12시간' when gap_s < 24*3600 then '4) 12~24시간'
                    when gap_s < 72*3600 then '5) 1~3일' else '6) 3일 이상' end as gap_bin,
               count(*) filter (where kind = 'moved' and cls not in ('overlap_error','unobservable_gap')) as moved,
               count(*) filter (where cls = 'stayed') as stayed
        from pairs_final group by all order by 1, 2""")
    gap_bins.to_csv(OUT / "gap_bins.csv", index=False, encoding="utf-8-sig")

    # 짧은 창(2시간 이하)의 무인 이동은 이동 시각을 거의 특정한다 → 차량 운영 시간대 근사
    hours = q(f"""
        with h as (select generate_series as hr from generate_series(0, 23)),
        r as (select hour(ts) as hr, count(*) n from trips group by 1),
        a as (select hour(t0) as hr, count(*) n from pairs_final where cls in {core_set} group by 1),
        b as (select hour(t1) as hr, count(*) n from pairs_final where cls in {core_set} group by 1),
        s as (select hour(t0 + to_seconds(cast(gap_s / 2 as bigint))) as hr, count(*) n
              from pairs_final where cls = 'moved_plausible' and gap_s <= 7200 group by 1)
        select h.hr as hour, coalesce(r.n, 0) rentals, coalesce(a.n, 0) moved_after_return_hour,
               coalesce(b.n, 0) moved_before_rental_hour, coalesce(s.n, 0) short_window_move_mid_hour
        from h left join r using (hr) left join a using (hr) left join b using (hr) left join s using (hr)
        order by 1""")
    hours.to_csv(OUT / "hourly_profile.csv", index=False, encoding="utf-8-sig")

    station_flow = q(f"""
        with outm as (select from_station sid, year(t1) y, count(*) n, sum(to_elev - from_elev) dh
                      from pairs_final where cls in {core_set} group by all),
             inm as (select to_station sid, year(t1) y, count(*) n from pairs_final where cls in {core_set} group by all),
             rent as (select o sid, year(ts) y, count(*) n from trips group by all),
             ret as (select d sid, year(te) y, count(*) n from trips group by all)
        select coalesce(rent.sid, ret.sid) as station_id, coalesce(rent.y, ret.y) as year,
               coalesce(rent.n, 0) as rentals, coalesce(ret.n, 0) as returns,
               coalesce(outm.n, 0) as moved_out, coalesce(inm.n, 0) as moved_in
        from rent full join ret on rent.sid = ret.sid and rent.y = ret.y
        left join outm on outm.sid = coalesce(rent.sid, ret.sid) and outm.y = coalesce(rent.y, ret.y)
        left join inm on inm.sid = coalesce(rent.sid, ret.sid) and inm.y = coalesce(rent.y, ret.y)
        order by 2, 1""")
    station_flow = station_flow.merge(stations[["station_id", "name", "district", "elev_m", "lat", "lon", "is_ops_center"]],
                                      on="station_id", how="left")
    station_flow["net_moved_in"] = station_flow["moved_in"] - station_flow["moved_out"]
    station_flow["moved_in_per_rental"] = station_flow["moved_in"] / station_flow["rentals"].where(station_flow["rentals"] > 0)
    station_flow.to_csv(OUT / "station_year_flows.csv", index=False, encoding="utf-8-sig")

    district_matrix = q(f"""select year(t1) as year, from_district, to_district, count(*) n, sum(dist_km) bike_km
                            from pairs_final where cls in {core_set} group by all order by 1, 4 desc""")
    district_matrix.to_csv(OUT / "district_move_matrix.csv", index=False, encoding="utf-8-sig")

    daily = q(f"""
        select service_date, count(*) as moved, count(distinct from_station) as pickup_stations,
               count(distinct to_station) as drop_stations, sum(dist_km) as bike_km
        from pairs_final where cls in {core_set} group by 1 order by 1""")
    rentals_daily = q(f"select cast(ts - interval {DAY_START_HOUR} hour as date) as service_date, count(*) as rentals from trips group by 1")
    daily = rentals_daily.merge(daily, on="service_date", how="left").fillna({"moved": 0})
    daily.to_csv(OUT / "daily_moves.csv", index=False, encoding="utf-8-sig")

    # 고도: 사람의 이동과 무인 이동의 높이 변화
    elev = q(f"""
        select year(t.ts) as year, 'rental_trip' as flow,
               count(*) n,
               avg(case when b.elev_m - a.elev_m < -5 then 1.0 else 0.0 end) share_down,
               avg(case when b.elev_m - a.elev_m > 5 then 1.0 else 0.0 end) share_up,
               sum(b.elev_m - a.elev_m) total_dh_m
        from trips t join st a on a.station_id = t.o join st b on b.station_id = t.d
        where t.o <> t.d group by all
        union all
        select year(t1), 'unrecorded_move', count(*),
               avg(case when to_elev - from_elev < -5 then 1.0 else 0.0 end),
               avg(case when to_elev - from_elev > 5 then 1.0 else 0.0 end),
               sum(to_elev - from_elev)
        from pairs_final where cls in {core_set} and from_elev is not null and to_elev is not null group by all
        order by 1, 2""")
    elev.to_csv(OUT / "elevation_flows.csv", index=False, encoding="utf-8-sig")

    # 같은 운영일·같은 출발·도착 거점으로 함께 옮겨진 대수(차량 적재 묶음 근사)
    con.execute(f"""
        copy (select service_date, from_station, to_station, count(*) as bikes, sum(dist_km) as bike_km,
                     min(t0) as first_return, max(t1) as last_rental
              from pairs_final where cls in {core_set} group by all)
        to '{(OUT / 'moves_by_day_pair.parquet').as_posix()}' (format parquet)""")
    batch_sizes = q(f"""
        select year(service_date) as year,
               case when bikes = 1 then '1대' when bikes = 2 then '2대' when bikes <= 4 then '3~4대'
                    when bikes <= 9 then '5~9대' else '10대 이상' end as batch,
               count(*) as groups, sum(bikes) as bikes
        from '{(OUT / 'moves_by_day_pair.parquet').as_posix()}' group by all order by 1, 2""")
    batch_sizes.to_csv(OUT / "batch_sizes.csv", index=False, encoding="utf-8-sig")

    audit["definitions"] = {
        "pair": "같은 자전거의 연속 두 이용(대여 시각순). 반납 거점·시각 → 다음 대여 거점·시각",
        "stayed": "반납 거점 = 다음 대여 거점",
        "moved_plausible": "다른 거점, 간격 5분 이상·3일 이하, 직선속도 60km/h 이하, 운영센터 무관, 좌표 있는 거점",
        "moved_after_long_idle": "위 조건이나 간격 3일 초과(정비·보관 후 재배치 가능성)",
        "moved_core": "moved_plausible + moved_after_long_idle (재배치 추정 핵심 집합)",
        "moved_ops_center": f"출발 또는 도착이 운영센터 {OPS_CENTERS}",
        "moved_implausible_fast": "간격 5분 미만 또는 직선속도 60km/h 초과(기록 오류 후보)",
        "unobservable_gap": f"반납~다음 대여 사이가 출발 기록 결측기간 {UNOBSERVED}에 걸침",
        "overlap_error": "다음 대여가 직전 반납보다 먼저 시작(기록 오류)",
        "service_date": f"다음 대여 시각에서 {DAY_START_HOUR}시간을 뺀 날짜",
        "elevation": "Copernicus GLO-30 DSM, 거점 주변 3x3 격자 최솟값(지면 근사)",
        "batch": "같은 출발거점(또는 같은 출발·도착 쌍)에서 [반납, 다음대여] 창이 다른 무인 이동과 겹침",
    }
    audit["inputs"]["dem_sha256"] = sha256(RAW / "elevation" / "Copernicus_DSM_COG_10_N35_00_E128_00_DEM.tif")
    audit["runtime_s"] = round(time.time() - t_start, 1)
    audit["versions"] = {"python": sys.version.split()[0], "duckdb": duckdb.__version__, "pandas": pd.__version__}
    (OUT / "audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(audit["rows"], ensure_ascii=False))
    print(yearly.to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
