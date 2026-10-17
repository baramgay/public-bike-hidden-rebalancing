"""관측된 무인 이동(재배치 추정)을 하루 단위로 묶어 차량 운행거리를 추정한다.

같은 운영일(다음 대여 시각 기준)의 수거 거점별 대수·배치 거점별 대수를 시뮬레이터와 같은
탐욕 경로(적재 용량별, 직선거리, 운영센터 출발·복귀)로 이으면 '그날 옮겨진 자전거를 옮기는 데
필요한 최소에 가까운 거리'가 된다. 실제 차량은 낮에도 여러 번 나가고 경로가 최적이 아니므로
실제 운행거리는 이보다 길다(하한 성격). 도로 우회계수는 별도 민감도로 곱한다.
"""
from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from simulate_rebalancing import route_km  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
CHAINS = ROOT / "data" / "processed" / "bike_chains"
OUT = ROOT / "data" / "processed" / "rebalancing_sim"
DEPOT = 243
CAPACITIES = (10, 20, 30)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    st = pd.read_csv(CHAINS / "stations.csv").set_index("station_id")
    lat0, lon0 = 35.22, 128.65
    xy_all = {s: np.array([(r.lon - lon0) * 111.32 * np.cos(np.radians(lat0)), (r.lat - lat0) * 110.57])
              for s, r in st.iterrows()}
    con = duckdb.connect()
    moves = con.execute(f"""
        select service_date, from_station, to_station, count(*) as n
        from '{(CHAINS / 'pairs.parquet').as_posix()}'
        where cls in ('moved_plausible', 'moved_after_long_idle')
        group by all""").df()
    sids = sorted(set(moves["from_station"]) | set(moves["to_station"]) | {DEPOT})
    idx = {s: i for i, s in enumerate(sids)}
    xy = np.array([xy_all[s] for s in sids])
    rows = []
    for day, g in moves.groupby("service_date"):
        pick = g.groupby("from_station")["n"].sum()
        drop = g.groupby("to_station")["n"].sum()
        row = {"service_date": day, "moved": int(g["n"].sum()), "pickup_stations": len(pick), "drop_stations": len(drop)}
        for cap in CAPACITIES:
            row[f"route_km_cap{cap}"] = route_km({idx[s]: int(n) for s, n in pick.items()},
                                                 {idx[s]: int(n) for s, n in drop.items()}, xy, idx[DEPOT], cap)
        rows.append(row)
    out = pd.DataFrame(rows)
    out.to_csv(OUT / "observed_truck_km_daily.csv", index=False, encoding="utf-8-sig")
    out["year"] = pd.to_datetime(out["service_date"]).dt.year
    summ = out.groupby("year").agg(days=("moved", "size"), moved_per_day=("moved", "mean"),
                                   **{f"km_cap{c}_per_day": (f"route_km_cap{c}", "mean") for c in CAPACITIES},
                                   **{f"km_cap{c}_year": (f"route_km_cap{c}", "sum") for c in CAPACITIES})
    summ.to_csv(OUT / "observed_truck_km_yearly.csv", encoding="utf-8-sig")
    print(summ.round(1).to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
