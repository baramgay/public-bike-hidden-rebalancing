"""자전거 번호 연쇄로 거점별 '자전거가 있던 시간'의 하한·상한을 복원한다.

재고 기록이 없어도 같은 자전거의 반납→다음 대여가 같은 거점이면 그 사이 자전거는 그 거점에 있었다.
- 확실(L): 같은 거점 대기 중 간격 24시간 이하. 24시간을 넘는 대기는 정비 수거 후 되돌림 가능성이 있어 '가능'으로 둔다.
- 가능(P): 다른 거점으로 옮겨진 쌍은 반납 거점·다음 대여 거점 모두에 [반납, 다음 대여] 동안 있었을 수 있다.
  결측기간에 걸친 쌍, 자전거의 첫 이용 전·마지막 이용 후 7일도 '가능'으로 둔다.
- 하한 가용: L>=1 인 시간, 상한 가용: L+P>=1 인 시간. 상한이 0이면 '기록상 자전거가 있을 수 없던 시간'.
정비 등으로 기록 없이 들렀다 나간 자전거는 보이지 않으므로 상한도 엄밀한 상한은 아니다.

입력: data/processed/bike_chains/{pairs,trips_valid}.parquet (trace_bike_chains.py 출력)
출력: data/processed/station_inventory/
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[2]
CHAINS = ROOT / "data" / "processed" / "bike_chains"
OUT = ROOT / "data" / "processed" / "station_inventory"
CERTAIN_MAX_GAP_S = 24 * 3600
EDGE_DAYS = 7
SERVICE_HOURS = (5, 24)  # 05:00~24:00 가용시간 측정
EVAL_START, EVAL_END = "2023-01-08", "2025-12-24"
EVAL_EXCLUDE = ("2025-06-24", "2025-08-07")  # 7월 출발기록 결측 앞뒤


def main() -> int:
    t_start = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    tmp = ROOT / ".tmp"
    con = duckdb.connect()
    con.execute(f"SET temp_directory='{tmp.as_posix()}'")
    con.execute("SET preserve_insertion_order=false")
    pairs = (CHAINS / "pairs.parquet").as_posix()
    trips = (CHAINS / "trips_valid.parquet").as_posix()

    # 구간 → (거점, 시각, dL, dP) 사건
    con.execute(f"""
        create table iv as
        select from_station as sid, t0 as a, t1 as b, 1 as certain
        from '{pairs}' where cls = 'stayed' and gap_s <= {CERTAIN_MAX_GAP_S}
        union all
        select from_station, t0, t1, 0 from '{pairs}' where cls = 'stayed' and gap_s > {CERTAIN_MAX_GAP_S}
        union all
        select from_station, t0, t1, 0 from '{pairs}' where cls <> 'stayed' and cls <> 'overlap_error'
        union all
        select to_station, t0, t1, 0 from '{pairs}' where cls <> 'stayed' and cls <> 'overlap_error'
        union all
        select o, ts - interval {EDGE_DAYS} day, ts, 0 from (
            select bike, arg_min(o, ts) as o, min(ts) as ts from '{trips}' group by bike)
        union all
        select d, te, te + interval {EDGE_DAYS} day, 0 from (
            select bike, arg_max(d, te) as d, max(te) as te from '{trips}' group by bike)""")
    counts = dict(con.execute("select certain, count(*) from iv group by 1").fetchall())

    lo, hi = SERVICE_HOURS
    con.execute(f"""
        create table ev as
        select sid, a as t, case when certain = 1 then 1 else 0 end as dl, case when certain = 1 then 0 else 1 end as dp
        from iv where b > a
        union all
        select sid, b, case when certain = 1 then -1 else 0 end, case when certain = 1 then 0 else -1 end
        from iv where b > a
        union all
        -- 측정 시간대의 매시 정각 경계(구간을 시간 단위로 자른다)
        select s.sid, d.day + to_hours(h.hr), 0, 0
        from (select distinct sid from iv) s
        cross join (select cast(range as date) as day from range(date '{EVAL_START}', date '{EVAL_END}' + interval 1 day, interval 1 day)) d
        cross join (select range as hr from range({lo}, {hi} + 1)) h""")
    con.execute("drop table iv")

    # 같은 시각의 사건을 먼저 합쳐 시각을 유일하게 만든 뒤 누적한다(동시각 정렬 모호성 제거).
    con.execute(f"""
        create table seg as
        with g as (select sid, t, sum(dl) as dl, sum(dp) as dp from ev group by sid, t),
        c as (
            select sid, t,
                   sum(dl) over w as l, sum(dp) over w as p,
                   lead(t) over w2 as t_next
            from g
            window w as (partition by sid order by t rows between unbounded preceding and current row),
                   w2 as (partition by sid order by t))
        select sid, cast(t as date) as day, hour(t) as hr, l, p, epoch(t_next - t) as dur
        from c
        where t_next > t and hour(t) >= {lo} and hour(t) < {hi}
          and cast(t as date) between date '{EVAL_START}' and date '{EVAL_END}'
          and not (cast(t as date) between date '{EVAL_EXCLUDE[0]}' and date '{EVAL_EXCLUDE[1]}')""")
    neg = con.execute("select count(*) from seg where l < 0 or p < 0").fetchone()[0]
    if neg:
        raise SystemExit(f"음수 재고 구간 {neg}건: 사건 정렬 오류")

    con.execute(f"""
        copy (
            select sid as station_id, day, hr as hour,
                   cast(sum(dur) as integer) as seconds,
                   cast(sum(dur) filter (where l >= 1) as integer) as sec_certain,
                   cast(sum(dur) filter (where l + p >= 1) as integer) as sec_possible,
                   sum(l * dur) / 3600.0 as bike_hours_certain,
                   sum((l + p) * dur) / 3600.0 as bike_hours_possible
            from seg group by all)
        to '{(OUT / 'station_hour_availability.parquet').as_posix()}' (format parquet)""")
    con.execute("drop table seg")
    hourly = (OUT / "station_hour_availability.parquet").as_posix()
    bad_hours = con.execute(f"select count(*) from '{hourly}' where seconds <> 3600").fetchone()[0]

    daily = con.execute(f"""
        copy (select station_id, day, sum(seconds) as seconds,
                     coalesce(sum(sec_certain), 0) as sec_certain, coalesce(sum(sec_possible), 0) as sec_possible,
                     coalesce(sum(sec_certain) filter (where hour between 7 and 9 or hour between 17 and 19), 0) as peak_sec_certain,
                     coalesce(sum(sec_possible) filter (where hour between 7 and 9 or hour between 17 and 19), 0) as peak_sec_possible,
                     sum(seconds) filter (where hour between 7 and 9 or hour between 17 and 19) as peak_seconds,
                     sum(bike_hours_certain) / sum(seconds / 3600.0) as avg_bikes_certain
              from '{hourly}' group by all)
        to '{(OUT / 'station_day_availability.parquet').as_posix()}' (format parquet)""")
    summary = con.execute(f"""
        select year(day) as year, count(*) as station_days,
               sum(sec_certain) / sum(seconds) as avail_certain,
               sum(sec_possible) / sum(seconds) as avail_possible,
               sum(peak_sec_certain) / sum(peak_seconds) as peak_avail_certain,
               sum(peak_sec_possible) / sum(peak_seconds) as peak_avail_possible
        from '{(OUT / 'station_day_availability.parquet').as_posix()}' group by 1 order by 1""").df()
    summary.to_csv(OUT / "yearly_availability.csv", index=False, encoding="utf-8-sig")

    audit = {
        "interval_counts": {"certain": int(counts.get(1, 0)), "possible": int(counts.get(0, 0))},
        "hours_not_3600s": int(bad_hours),
        "definitions": {
            "certain": f"같은 거점 대기, 간격 {CERTAIN_MAX_GAP_S // 3600}시간 이하",
            "possible": "24시간 초과 대기, 다른 거점 이동 쌍의 양 끝 거점, 결측기간 쌍, 첫 이용 전·마지막 이용 후 7일",
            "service_hours": f"{lo:02d}:00~{hi:02d}:00",
            "evaluation": f"{EVAL_START}~{EVAL_END}, 제외 {EVAL_EXCLUDE[0]}~{EVAL_EXCLUDE[1]}",
            "peak": "07~10시, 17~20시(시작 시각 7,8,9,17,18,19)",
        },
        "runtime_s": round(time.time() - t_start, 1),
        "versions": {"duckdb": duckdb.__version__},
    }
    (OUT / "audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(audit, ensure_ascii=False, indent=1))
    print(summary.to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
