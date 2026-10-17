"""Current-connection scenario with an explicit five-district facility gate and the
pre-registered v2 vulnerability flags (per-indicator quantiles, no composite score).

No network access. Source files are read only. Run from the project root:
python scripts/analysis/build_accessibility_scenarios.py --write-lock   # once, before any flags
python scripts/analysis/build_accessibility_scenarios.py
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

DISTRICTS = ("의창구", "성산구", "마산합포구", "마산회원구", "진해구")
CATEGORIES = ("medical", "pharmacy", "grocery")
DEFINITION_ID = "current_connection_equal_domain_rank_v1"
WALK_RADIUS_M = 500.0  # straight-line boarding/egress scenario, not walking time
ROOT = Path(__file__).resolve().parents[2]
API_RUN = "20261016T150727234763Z"


def valid_coordinates(frame: pd.DataFrame) -> pd.Series:
    """Nonnullable validity mask; the local box is not an administrative boundary."""
    lat = pd.to_numeric(frame["lat"], errors="coerce")
    lon = pd.to_numeric(frame["lon"], errors="coerce")
    return (lat.between(34.9, 35.5) & lon.between(128.3, 129.1)).fillna(False).astype(bool)


def all_verified_true(values: pd.Series) -> bool:
    """Only actual boolean True values establish completed evidence review."""
    return bool(len(values)) and all(isinstance(value, (bool, np.bool_)) and bool(value)
                                     for value in values)


def distances_m(origins: pd.DataFrame, destinations: pd.DataFrame) -> np.ndarray:
    """Haversine metres; invalid coordinates must be removed by the caller."""
    a = np.radians(origins[["lat", "lon"]].to_numpy(dtype=float))
    b = np.radians(destinations[["lat", "lon"]].to_numpy(dtype=float))
    h = np.sin((a[:, None, 0] - b[None, :, 0]) / 2) ** 2
    h += (np.cos(a[:, None, 0]) * np.cos(b[None, :, 0])
          * np.sin((a[:, None, 1] - b[None, :, 1]) / 2) ** 2)
    return 2 * 6371008.8 * np.arcsin(np.sqrt(np.clip(h, 0, 1)))


def select_vulnerable(scores: pd.Series, share: float) -> pd.Series:
    """Keep boundary ties together; an all-tied set has no identified subgroup."""
    result = pd.Series(pd.NA, index=scores.index, dtype="boolean")
    known = scores.dropna()
    if known.nunique() <= 1:
        return result
    n = max(1, int(np.ceil(len(known) * share)))
    threshold = known.nlargest(n).iloc[-1]
    result.loc[known.index] = known >= threshold
    return result


def rank_component(values: pd.Series) -> pd.Series:
    """Average-tie ranks scaled to [0,1]; higher means worse access."""
    if len(values) <= 1:
        return pd.Series(.5, index=values.index)
    return (values.rank(method="average") - 1) / (len(values) - 1)


def transit_quality(stops: pd.DataFrame, routes: pd.DataFrame) -> dict:
    """Route-stop rows retain repeated visits; only dimension joins are unique."""
    required_stops = {"nodeid", "lat", "lon", "reference_date"}
    required_routes = {"routeid", "nodeid", "nodeord", "updowncd", "reference_date"}
    missing = sorted((required_stops - set(stops)) | (required_routes - set(routes)))
    if missing:
        return {"missing_columns": missing, "valid": False}
    order = pd.to_numeric(routes.nodeord, errors="coerce")
    bad_order = order.isna() | (order <= 0) | (order.mod(1) != 0)
    duplicate_stops = int(stops.duplicated("nodeid").sum())
    canonical_order = routes.assign(_order=order)
    duplicate_order = int(canonical_order.duplicated(["routeid", "updowncd", "_order"]).sum())
    unknown = sorted(set(routes.nodeid.dropna()) - set(stops.nodeid.dropna()))
    blank_stop_id = int(stops.nodeid.fillna("").eq("").sum())
    blank_route_fields = int(routes[["routeid", "nodeid", "updowncd"]]
                             .fillna("").eq("").any(axis=1).sum())
    bad_stop_coords = int((~valid_coordinates(stops)).sum())
    joined_rows = None
    if not duplicate_stops:
        joined_rows = len(routes.merge(stops[["nodeid"]], on="nodeid", how="left", validate="many_to_one"))
    q = {
        "missing_columns": [], "stop_rows": len(stops), "unique_stop_ids": int(stops.nodeid.nunique()),
        "route_stop_rows": len(routes), "unique_route_ids": int(routes.routeid.nunique()),
        "duplicate_stop_ids": duplicate_stops, "blank_stop_ids": blank_stop_id,
        "invalid_stop_coordinates": bad_stop_coords, "blank_route_key_rows": blank_route_fields,
        "duplicate_stop_coordinates": int(stops.duplicated(["lat", "lon"]).sum()),
        "invalid_route_orders": int(bad_order.sum()), "duplicate_route_direction_order": duplicate_order,
        "duplicate_full_route_stop_rows": int(routes.duplicated().sum()),
        "repeat_route_node_visits": int(routes.duplicated(["routeid", "nodeid"]).sum()),
        "repeat_route_direction_node_visits": int(routes.duplicated(["routeid", "updowncd", "nodeid"]).sum()),
        "unknown_stop_ids": len(unknown), "unknown_stop_id_examples": unknown[:10],
        "joined_rows": joined_rows,
        "virtual_name_stops": int(stops.get("nodenm", pd.Series("", index=stops.index)).str.contains("가상", na=False).sum()),
        "stop_reference_dates": sorted(stops.reference_date.dropna().unique().tolist()),
        "route_reference_dates": sorted(routes.reference_date.dropna().unique().tolist()),
        "updowncd_counts": routes.updowncd.value_counts(dropna=False).to_dict(),
        "coordinate_box": {"lat": [34.9, 35.5], "lon": [128.3, 129.1]},
    }
    if "nodeno" in stops:
        nodeno = stops.nodeno.dropna()
        q["duplicate_nonblank_nodeno"] = int(nodeno[nodeno.ne("")].duplicated().sum())
    q["nodeid_matches_observed_CWB_nine_digit_pattern"] = int(stops.nodeid.fillna("").str.fullmatch(r"CWB\d{9}").sum())
    q["stop_coordinate_bounds"] = stops[["lat", "lon"]].apply(pd.to_numeric, errors="coerce").agg(["min", "max"]).where(lambda x: x.notna(), None).to_dict()
    gaps = [int((group._order.sort_values().diff().dropna() > 1).sum())
            for _, group in canonical_order.groupby(["routeid", "updowncd"])]
    q["route_direction_groups"] = len(gaps)
    q["route_direction_order_gaps"] = sum(gaps)
    q["route_node_coverage_stop_ids"] = int(routes.nodeid.nunique())
    if {"lat", "lon"} <= set(routes):
        q["invalid_route_stop_coordinates"] = int((~valid_coordinates(routes)).sum())
        if not duplicate_stops:
            joined = routes.merge(stops[["nodeid", "lat", "lon"]], on="nodeid", how="left", validate="many_to_one", suffixes=("", "_stop"))
            # Paired coordinate difference, not an n-by-n distance matrix.
            x = np.radians(joined[["lat", "lon"]].apply(pd.to_numeric, errors="coerce").to_numpy(float))
            y = np.radians(joined[["lat_stop", "lon_stop"]].apply(pd.to_numeric, errors="coerce").to_numpy(float))
            h = np.sin((x[:, 0] - y[:, 0]) / 2) ** 2 + np.cos(x[:, 0]) * np.cos(y[:, 0]) * np.sin((x[:, 1] - y[:, 1]) / 2) ** 2
            delta = 2 * 6371008.8 * np.arcsin(np.sqrt(np.clip(h, 0, 1)))
            q["route_stop_coordinate_delta_over_1m_rows"] = int((delta > 1).sum())
            q["route_stop_coordinate_delta_max_m"] = float(np.nanmax(delta)) if np.isfinite(delta).any() else None
    dates_ok = (not stops.reference_date.isna().any() and not routes.reference_date.isna().any()
                and len(q["stop_reference_dates"]) == 1 and len(q["route_reference_dates"]) == 1
                and q["stop_reference_dates"] == q["route_reference_dates"]
                and pd.notna(pd.to_datetime(q["stop_reference_dates"][0], errors="coerce")))
    q["valid"] = not any((duplicate_stops, blank_stop_id, blank_route_fields, bad_stop_coords,
                           int(bad_order.sum()), duplicate_order, len(unknown),
                           q.get("invalid_route_stop_coordinates", 0))) and bool(dates_ok) and len(stops) > 0 and len(routes) > 0
    return q


def build_accessibility(stations: pd.DataFrame, stops: pd.DataFrame,
                        routes: pd.DataFrame, facilities: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Validate evidence before constructing the frozen current-scenario index.

    routes contains route-stop rows, not the route catalogue. Facility completeness,
    functional classification and rights must be established by source review and
    passed explicitly; a point in each district alone is insufficient evidence.
    """
    stations, stops, routes, facilities = [x.copy().reset_index(drop=True) for x in (stations, stops, routes, facilities)]
    station_required = {"station_id", "district", "lat", "lon", "reference_date"}
    facility_required = {"facility_id", "district", "category", "lat", "lon", "reference_date",
                         "source_url", "rights", "coverage_complete", "functional_verified", "category_definition"}
    missing = []
    for label, data, columns in (("stations", stations, station_required), ("facilities", facilities, facility_required)):
        absent = columns - set(data)
        if absent:
            missing.append(label + ": missing columns " + ",".join(sorted(absent)))
            for col in absent:
                data[col] = pd.NA
    out = stations[["station_id", "district"]].copy()
    q = transit_quality(stops, routes)
    if not q["valid"]:
        missing.append("transit: invalid or incomplete route-stop evidence; see transit_quality")
    station_valid = valid_coordinates(stations)
    station_invalid = int((~station_valid).sum())
    if station_invalid or stations.station_id.isna().any() or stations.station_id.duplicated().any() or not len(stations):
        missing.append("stations: invalid coordinates, missing/duplicate IDs or empty input")
    if not stations.district.isin(DISTRICTS).all():
        missing.append("stations: unrecognized district")
    station_dates = pd.to_datetime(stations.reference_date, errors="coerce")
    if station_dates.isna().any() or stations.reference_date.nunique() != 1:
        missing.append("stations: missing or inconsistent snapshot reference date")
    out["station_reference_date"] = stations.reference_date
    ref = q.get("stop_reference_dates", [])
    out["reference_date"] = ref[0] if len(ref) == 1 else pd.NA
    out["definition_id"] = DEFINITION_ID
    for col in ("nearest_stop_m", "bus_component", "facility_component", "combined_component",
                "bus_destination_categories", *("nearest_" + c + "_m" for c in CATEGORIES)):
        out[col] = np.nan
    for col in ("vulnerable", "vulnerable_20", "vulnerable_30", "vulnerable_bus_only", "vulnerable_facility_only"):
        out[col] = pd.Series(pd.NA, index=out.index, dtype="boolean")
    # A valid stop-distance diagnostic remains available when facilities are blocked.
    if {"nodeid", "lat", "lon"} <= set(stops):
        good_stops = stops[valid_coordinates(stops)].drop_duplicates("nodeid")
        if len(good_stops) and station_valid.any():
            distance = distances_m(stations[station_valid], good_stops)
            out.loc[station_valid, "nearest_stop_m"] = distance.min(axis=1)
    valid_fac = valid_coordinates(facilities)
    # G4 (v2): only rows with BOTH coordinates absent and a recorded address are an
    # explicit, counted exclusion; every other invalid coordinate still blocks.
    address = facilities["address"] if "address" in facilities else pd.Series(pd.NA, index=facilities.index)
    excluded_fac = (facilities.lat.isna() & facilities.lon.isna()
                    & address.fillna("").astype(str).str.strip().ne("")).astype(bool)
    if facilities.facility_id.isna().any() or facilities.duplicated(["category", "facility_id"]).any():
        missing.append("facilities: missing/duplicate IDs within category")
    if not facilities.district.isin(DISTRICTS).all():
        missing.append("facilities: unrecognized district; geocoding/boundary QA required")
    coverage = {}
    for district in DISTRICTS:
        coverage[district] = {}
        for category in CATEGORIES:
            mask = (facilities.district == district) & (facilities.category == category)
            part = facilities[mask]
            checks = {
                "rows": len(part), "valid_coordinates": int(valid_fac[mask].sum()),
                "excluded_missing_coordinates": int(excluded_fac[mask].sum()),
                "invalid_coordinates": int((~valid_fac[mask] & ~excluded_fac[mask]).sum()),
                "complete": all_verified_true(part.coverage_complete),
                "functional_verified": all_verified_true(part.functional_verified),
            }
            coverage[district][category] = checks
            if not len(part):
                missing.append(f"{district}/{category}: no verified five-district source coverage")
            elif (checks["invalid_coordinates"] or not checks["valid_coordinates"]
                  or not checks["complete"] or not checks["functional_verified"]):
                missing.append(f"{district}/{category}: coordinates, complete coverage or functional definition unverified")
    for category in CATEGORIES:
        part = facilities[facilities.category == category]
        dates = pd.to_datetime(part.reference_date, errors="coerce")
        if part.empty or dates.isna().any() or part.reference_date.nunique() != 1:
            missing.append(f"{category}: missing/inconsistent five-district reference date")
        if part.category_definition.fillna("").eq("").any() or part.category_definition.nunique() != 1:
            missing.append(f"{category}: inconsistent or missing functional category definition")
        if (part.rights.fillna("").str.lower().isin(["", "unknown", "unverified"]).any()
                or not part.source_url.fillna("").str.startswith("https://").all()):
            missing.append(f"{category}: rights or official source URL unverified")
    status = {
        "ready": not missing, "classification_ready": False,
        "missing_inputs": missing, "coverage_by_district": coverage, "transit_quality": q,
        "station_rows": len(stations), "station_invalid_coordinates": station_invalid,
        "station_coordinate_qa_by_district": {
            d: {"rows": int((stations.district == d).sum()),
                "invalid_coordinates": int((~station_valid & stations.district.eq(d)).sum())}
            for d in DISTRICTS},
        "definition_id": DEFINITION_ID, "scenario": "current_connection_mixed_source_snapshots",
        "denominator": "analysis_stations", "resident_grid_available": False,
        "population_claims_allowed": False, "historical_vulnerability_claims_allowed": False,
        "boarding_egress_straight_radius_m": WALK_RADIUS_M,
        "facility_reference_dates": {c: sorted(facilities.loc[facilities.category == c, "reference_date"].dropna().unique().tolist()) for c in CATEGORIES},
        "tie_rule": "include all boundary ties; all-tied scores yield unknown vulnerability",
        "excluded_missing_coordinate_rows": int(excluded_fac.sum()),
    }
    if missing:
        return out, status
    sb = distances_m(stations, stops)
    out["nearest_stop_m"] = sb.min(axis=1)
    stop_categories = np.zeros((len(stops), len(CATEGORIES)), dtype=bool)
    for j, category in enumerate(CATEGORIES):
        fs = facilities[(facilities.category == category) & valid_fac]
        out["nearest_" + category + "_m"] = distances_m(stations, fs).min(axis=1)
        stop_categories[:, j] = (distances_m(stops, fs) <= WALK_RADIUS_M).any(axis=1)
    # Routes are directional ordered visits. Reachability excludes the boarding
    # visit itself and permits no transfers; repeated visits are not deduplicated.
    index = {node: i for i, node in enumerate(stops.nodeid)}
    reachable = np.zeros_like(stop_categories)
    ordered = routes.assign(_order=pd.to_numeric(routes.nodeord)).sort_values(["routeid", "updowncd", "_order"])
    for _, group in ordered.groupby(["routeid", "updowncd"], sort=True):
        downstream = np.zeros(len(CATEGORIES), dtype=bool)
        for node in reversed(group.nodeid.tolist()):
            k = index[node]
            reachable[k] |= downstream
            downstream |= stop_categories[k]
    boarding = sb <= WALK_RADIUS_M
    counts = np.array([reachable[row].any(axis=0).sum() if row.any() else 0 for row in boarding])
    out["bus_destination_categories"] = counts
    out["bus_component"] = (rank_component(out.nearest_stop_m) + rank_component(-out.bus_destination_categories)) / 2
    out["facility_component"] = sum(rank_component(out["nearest_" + c + "_m"]) for c in CATEGORIES) / len(CATEGORIES)
    out["combined_component"] = (out.bus_component + out.facility_component) / 2
    for share, col in ((.2, "vulnerable_20"), (.25, "vulnerable"), (.3, "vulnerable_30")):
        out[col] = select_vulnerable(out.combined_component, share)
    out["vulnerable_bus_only"] = select_vulnerable(out.bus_component, .25)
    out["vulnerable_facility_only"] = select_vulnerable(out.facility_component, .25)
    status["classification_ready"] = bool(out.vulnerable.notna().all())
    status["selected_counts"] = {c: int(out[c].sum()) for c in ("vulnerable_20", "vulnerable", "vulnerable_30")}
    return out, status


# ---- v2: pre-registered per-indicator quantile flags; no weights, no composite score ----
VULN_DEFINITION_ID = "bus_facility_quantile_flags_v2"
BUS_RADIUS_M = 300.0
PRIMARY_CARE_CODES = {"31": "의원", "21": "병원", "71": "보건소", "72": "보건지소", "73": "보건진료소"}
PHARMACY_CODES = {"81": "약국"}
FACILITY_FLAGS = {"flag_primary_care": "nearest_primary_care_m", "flag_pharmacy": "nearest_pharmacy_m",
                  "flag_market": "nearest_traditional_market_m"}
RULE = {
    "definition_id": VULN_DEFINITION_ID,
    "unit": "union of terminals marked 사용함 in the 2024년 and 2025년 sheets minus operating centers "
            "(is_ops_center in data/processed/bike_chains/stations.csv); centers stay in the table, unclassified; "
            "unknown center status blocks classification_ready",
    "reference_only_columns": ["elev_m"],
    "indicators": {"bus_trips_per_hour_300m": "lower_is_worse", "nearest_primary_care_m": "higher_is_worse",
                   "nearest_pharmacy_m": "higher_is_worse", "nearest_traditional_market_m": "higher_is_worse"},
    "bus_radius_m": 300,
    "route_rate": "leading weekday 운행횟수 / (막차출발 - 첫차출발 hours); unmatched routes add 0 and are counted",
    "route_match": "unique timetable number: exact routeno; duplicated number: routeno equal or 'number-' prefix whose "
                   "startnodenm contains 기점, then endnodenm contains 종점 if several; exactly one; one row per route",
    "flag": "worst ceil(n*q) boundary, all boundary ties included; all-tied indicator or missing value -> NA",
    "shares": [0.2, 0.25, 0.3], "main_share": 0.25, "facility_poor_min_flags": 2,
    "vulnerable": "bus_poor OR facility_poor", "vulnerable_both": "bus_poor AND facility_poor",
    "logic": "three-valued (Kleene)",
    "primary_care_type_codes": sorted(PRIMARY_CARE_CODES), "pharmacy_type_codes": sorted(PHARMACY_CODES),
    "market_definition": "all Changwon rows of the national traditional market standard data, 2025-11-10",
    "facility_snapshot_main": "HIRA 2024-12",
    "sensitivity": ["shares 0.20 and 0.30", "HIRA 2025-12 medical/pharmacy",
                    "unmatched routes at the maximum matched route rate"],
    "missing_coordinates": "facilities with both coordinates missing and an address are excluded and counted",
    "distance": "haversine metres, mean Earth radius 6371008.8",
    "weights": None,
}
RULE_MARKERS = ("<!-- vulnerability-rule:start -->", "<!-- vulnerability-rule:end -->")
HIRA_DIR = Path("data/raw/accessibility_facilities/grok_hira_changwon5_20261017")
HIRA_URL = "https://opendata.hira.or.kr/op/opc/selectOpenData.do?sno=11925"
MARKET_FILE = "changwon_traditional_markets_20251110_subset.csv"


def canonical_sha256(obj) -> str:
    text = json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def rule_section_sha256(doc_text: str) -> str:
    start, end = doc_text.index(RULE_MARKERS[0]), doc_text.index(RULE_MARKERS[1]) + len(RULE_MARKERS[1])
    return hashlib.sha256(doc_text[start:end].encode("utf-8")).hexdigest()


def verify_lock(lock: dict, doc_text: str) -> list[str]:
    """Empty list means code rule, lock and documented rule section all agree."""
    problems = []
    if lock.get("rule") != RULE or lock.get("rule_sha256") != canonical_sha256(RULE):
        problems.append("rule in code differs from locked rule")
    if lock.get("doc_rule_section_sha256") != rule_section_sha256(doc_text):
        problems.append("documented rule section differs from locked section")
    return problems


def quantile_flag(values: pd.Series, share: float, lower_is_worse: bool) -> pd.Series:
    """Worst ceil(n*q) boundary over known values, boundary ties kept, all-tied -> NA."""
    values = pd.to_numeric(values, errors="coerce").astype(float)
    return select_vulnerable(-values if lower_is_worse else values, share)


def classify(ind: pd.DataFrame, share: float) -> pd.DataFrame:
    flags = pd.DataFrame({"flag_bus": quantile_flag(ind.bus_trips_per_hour_300m, share, True)}, index=ind.index)
    for flag, column in FACILITY_FLAGS.items():
        flags[flag] = quantile_flag(ind[column], share, False)
    fac = flags[list(FACILITY_FLAGS)]
    hits, unknown = fac.fillna(False).astype(int).sum(axis=1), fac.isna().sum(axis=1)
    need = RULE["facility_poor_min_flags"]
    poor = pd.Series(pd.NA, index=ind.index, dtype="boolean")
    poor[hits >= need] = True
    poor[hits + unknown < need] = False
    flags["bus_poor"], flags["facility_poor"] = flags.flag_bus, poor
    flags["vulnerable"] = flags.bus_poor | poor
    flags["vulnerable_both"] = flags.bus_poor & poor
    return flags


def hhmm_hours(values: pd.Series) -> pd.Series:
    parts = values.fillna("").str.extract(r"^(\d{1,2}):(\d{2})$").astype(float)
    return parts[0] + parts[1] / 60


def route_rates(timetable: pd.DataFrame, catalogue: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """One row per current catalogue route; rate is NaN when no single timetable row matches."""
    t = timetable.reset_index(drop=True).copy()
    trips = pd.to_numeric(t["운행횟수"].fillna("").str.extract(r"^(\d+(?:\.\d+)?)")[0], errors="coerce")
    span = hhmm_hours(t["막차출발"]) - hhmm_hours(t["첫차출발"])
    t["rate"] = (trips / span).where(span > 0)
    headway = t["배차간격(분)"].fillna("").str.extract(r"^(\d+(?:\.\d+)?)(?:~(\d+(?:\.\d+)?))?").astype(float)
    t["headway_rate"] = 60 / headway.mean(axis=1)  # range midpoint; QA cross-check only
    duplicated = t["노선번호"].duplicated(keep=False)
    routeno = catalogue.routeno.fillna("")
    hits = []
    for i, row in t.iterrows():
        number = row["노선번호"]
        if not duplicated[i]:
            cand = catalogue[routeno == number]
        else:
            cand = catalogue[(routeno == number) | routeno.str.startswith(number + "-")]
            cand = cand[cand.startnodenm.fillna("").str.contains(row["기점"], regex=False)]
            if len(cand) > 1:
                cand = cand[cand.endnodenm.fillna("").str.contains(row["종점"], regex=False)]
        hits.append(cand.routeid.iloc[0] if len(cand) == 1 else None)
    t["routeid"] = hits
    clash = t.routeid.notna() & t.routeid.duplicated(keep=False)
    t.loc[clash, "routeid"] = None
    keep = ["routeid", "노선번호", "기점", "종점", "첫차출발", "막차출발", "운행횟수", "배차간격(분)", "rate", "headway_rate"]
    table = catalogue[["routeid", "routeno", "routetp", "startnodenm", "endnodenm"]].merge(
        t.dropna(subset=["routeid"])[keep], on="routeid", how="left", validate="one_to_one")
    known = table.rate.notna()
    both = t.rate.notna() & t.headway_rate.notna()
    qa = {"timetable_rows": len(t), "catalogue_routes": len(catalogue), "matched_routes": int(known.sum()),
          "unmatched_routes": table.loc[~known, "routeno"].tolist(),
          "timetable_rows_without_route": t.loc[t.routeid.isna(), "노선번호"].tolist(),
          "timetable_route_clashes": int(clash.sum()), "invalid_rate_rows": int(t.rate.isna().sum()),
          "rate_per_hour": table.rate.describe().to_dict(), "max_matched_rate": float(table.rate.max()),
          "headway_rate_correlation": float(t.rate[both].corr(t.headway_rate[both])),
          "median_rate_to_headway_rate": float((t.rate[both] / t.headway_rate[both]).median())}
    return table, qa


def bus_indicators(stations: pd.DataFrame, stops: pd.DataFrame, route_stops: pd.DataFrame,
                   rates: pd.Series) -> pd.DataFrame:
    """rates: routeid -> trips/hour, NaN when unmatched. A route counts once per station."""
    near = distances_m(stations, stops) <= BUS_RADIUS_M
    incidence = (pd.crosstab(route_stops.nodeid, route_stops.routeid)
                 .reindex(index=stops.nodeid, columns=rates.index, fill_value=0).to_numpy() > 0)
    serving = (near.astype(int) @ incidence.astype(int)) > 0
    known = rates.notna().to_numpy()
    return pd.DataFrame({"bus_stops_300m": near.sum(axis=1), "bus_routes_300m": serving.sum(axis=1),
                         "bus_routes_unmatched_300m": (serving & ~known).sum(axis=1),
                         "bus_trips_per_hour_300m": serving.astype(float) @ rates.fillna(0).to_numpy()},
                        index=stations.index)


def load_stations(path: Path) -> tuple[pd.DataFrame, dict]:
    """2024/2025 active terminals; coordinates from the latest active year's sheet."""
    active = {}
    for year in ("2024", "2025"):
        sheet = pd.read_excel(path, sheet_name=year + "년", dtype={"터미널번호": str})
        sheet = sheet[sheet["사용유무"] == "사용함"]
        if sheet["터미널번호"].duplicated().any():
            raise SystemExit(f"{year}: duplicate active terminal IDs; station table cannot be keyed")
        active[year] = sheet.set_index("터미널번호")
    ids = sorted(set(active["2024"].index) | set(active["2025"].index), key=lambda s: (len(s), s))
    rows = []
    for sid in ids:
        year = "2025" if sid in active["2025"].index else "2024"
        src = active[year].loc[sid]
        rows.append({"station_id": sid, "station_name": src["터미널명"], "district": src["구"],
                     "lat": float(src["위도"]), "lon": float(src["경도"]),
                     "active_2024": sid in active["2024"].index, "active_2025": sid in active["2025"].index,
                     "reference_date": year + "-12-31"})
    stations = pd.DataFrame(rows)
    stations["operating_years"] = np.where(stations.active_2024, "2024;2025", "2025")
    stations.loc[~stations.active_2025, "operating_years"] = "2024"
    both = active["2024"].join(active["2025"], how="inner", lsuffix="_24", rsuffix="_25")
    shift = distances_m(both[["위도_24", "경도_24"]].set_axis(["lat", "lon"], axis=1),
                        both[["위도_25", "경도_25"]].set_axis(["lat", "lon"], axis=1)).diagonal()
    qa = {"active_2024": len(active["2024"]), "active_2025": len(active["2025"]), "union": len(stations),
          "only_2024": int((~stations.active_2025).sum()), "only_2025": int((~stations.active_2024).sum()),
          "both_years": len(both), "both_years_max_coordinate_shift_m": float(shift.max()) if len(both) else None,
          "both_years_district_changes": int((both["구_24"] != both["구_25"]).sum()),
          "coordinate_source": "2025년 sheet when active in 2025, else 2024년 sheet"}
    return stations, qa


def load_hira(root: Path, snapshot: str) -> tuple[pd.DataFrame, dict]:
    """Primary care and pharmacies from the HIRA five-district extract; rows are never geocoded."""
    reference = {"2024-12": "2024-12-31", "2025-12": "2025-12-31"}[snapshot]
    parts, qa = [], {"snapshot": snapshot, "reference_date": reference}
    for kind, category, codes in (("hosp", "medical", PRIMARY_CARE_CODES), ("pharm", "pharmacy", PHARMACY_CODES)):
        path = root / HIRA_DIR / f"hira_{kind}_changwon5_{snapshot}.csv"
        raw = pd.read_csv(path, dtype=str, encoding="utf-8-sig")
        lat, lon = pd.to_numeric(raw["좌표(Y)"], errors="coerce"), pd.to_numeric(raw["좌표(X)"], errors="coerce")
        keep, absent = raw["종별코드"].isin(codes), lat.isna() | lon.isna()
        qa[kind] = {"file": path.name, "rows": len(raw), "unique_ids": int(raw["암호화요양기호"].nunique()),
                    "rows_by_district": raw["시군구코드명"].value_counts().to_dict(),
                    "type_counts": {f"{c} {n}": int(v) for (c, n), v in raw.groupby(["종별코드", "종별코드명"]).size().items()},
                    "included_rows": int(keep.sum()), "excluded_type_rows": int((~keep).sum()),
                    "lon_range_x": [float(lon.min()), float(lon.max())], "lat_range_y": [float(lat.min()), float(lat.max())],
                    "missing_coordinate_rows": int(absent.sum()),
                    "missing_coordinate_rows_without_address": int((absent & raw["주소"].fillna("").str.strip().eq("")).sum()),
                    "included_missing_coordinate_by_district": raw[keep & absent]["시군구코드명"].value_counts().to_dict()}
        part = raw[keep]
        parts.append(pd.DataFrame({
            "facility_id": "HIRA:" + part["암호화요양기호"], "district": part["시군구코드명"].str.replace(r"^창원", "", regex=True),
            "category": category, "lat": lat[keep], "lon": lon[keep], "reference_date": reference,
            "source_url": HIRA_URL, "rights": "KOGL type 1 attribution", "coverage_complete": True,
            "functional_verified": True, "category_definition": f"hira_type_codes_{'_'.join(sorted(codes))}",
            "address": part["주소"], "type_code": part["종별코드"], "type_name": part["종별코드명"],
            "facility_name": part["요양기관명"], "source_file": path.name}))
    return pd.concat(parts, ignore_index=True), qa


def load_markets(root: Path) -> pd.DataFrame:
    raw = pd.read_csv(root / "data/raw/accessibility_facilities" / MARKET_FILE, dtype=str, encoding="utf-8-sig")
    district = district_from_address(raw["소재지도로명주소"]).fillna(district_from_address(raw["소재지지번주소"]))
    return pd.DataFrame({
        "facility_id": [f"15012894:{i + 1}" for i in range(len(raw))], "district": district, "category": "grocery",
        "lat": pd.to_numeric(raw["위도"], errors="coerce"), "lon": pd.to_numeric(raw["경도"], errors="coerce"),
        "reference_date": raw["데이터기준일자"], "source_url": "https://www.data.go.kr/data/15012894/standard.do",
        "rights": "public-unrestricted", "coverage_complete": True, "functional_verified": True,
        "category_definition": "traditional_market_registry_20251110",
        "address": raw["소재지도로명주소"].fillna(raw["소재지지번주소"]), "type_code": pd.NA,
        "type_name": raw["시장유형"], "facility_name": raw["시장명"], "source_file": MARKET_FILE})


def district_from_address(values: pd.Series) -> pd.Series:
    compact = values.fillna("").str.replace(" ", "", regex=False)
    return compact.str.extract("(" + "|".join(DISTRICTS) + ")", expand=False)


def load_existing_facilities(root: Path) -> tuple[pd.DataFrame, list[Path]]:
    """Preserve available incomplete evidence; never assert missing coordinates."""
    folder = root / "data/raw/accessibility_facilities"
    sources = [
        ("changwon_uichang_seongsan_medical_20251117.csv", "medical", "2025-11-17", "15088969", "의료기관주소(도로명)"),
        ("changwon_masan_medical_20260101.csv", "medical", "2026-01-01", "15055453", "의료기관주소(도로명)"),
        ("changwon_uichang_seongsan_pharmacy_20260514.csv", "pharmacy", "2026-05-14", "15088971", "약국소재지(도로명)"),
        ("changwon_traditional_markets_20251110_subset.csv", "grocery", "2025-11-10", "15012894", "소재지도로명주소"),
    ]
    parts, paths = [], []
    for name, category, date, source, address in sources:
        path = folder / name
        if not path.exists():
            continue
        paths.append(path)
        encoding = "utf-8-sig" if category == "grocery" else "cp949"
        raw = pd.read_csv(path, encoding=encoding, dtype=str)
        district = district_from_address(raw[address])
        if "소재지지번주소" in raw:
            district = district.fillna(district_from_address(raw["소재지지번주소"]))
        part = pd.DataFrame({"facility_id": [f"{source}:{i + 1}" for i in range(len(raw))],
                             "district": district, "category": category,
                             "lat": pd.to_numeric(raw.get("위도", pd.Series(np.nan, index=raw.index)), errors="coerce"),
                             "lon": pd.to_numeric(raw.get("경도", pd.Series(np.nan, index=raw.index)), errors="coerce"),
                             "reference_date": date, "source_url": f"https://www.data.go.kr/data/{source}/fileData.do",
                             "rights": "public-unrestricted", "coverage_complete": False,
                             "functional_verified": False, "category_definition": "unverified_" + category,
                             "source_file": name})
        if category == "grocery":
            part["functional_verified"] = raw["취급품목"].str.contains("농산물|축산물|수산물|가공식품", na=False)
            part["category_definition"] = "traditional_market_food_candidate_only"
            part["source_url"] = "https://www.data.go.kr/data/15012894/standard.do"
        elif category == "pharmacy":
            part["functional_verified"] = True  # pharmacy presence, no opening-hour claim
        parts.append(part)
    return pd.concat(parts, ignore_index=True), paths


def compare_old_stops(old: pd.DataFrame, stops: pd.DataFrame) -> tuple[dict, pd.DataFrame]:
    """Audit an observed ID-prefix candidate crosswalk; differences are not closures."""
    old = old.rename(columns={"정류소아이디": "old_nodeid", "정류소명": "old_name", "위도": "old_lat", "경도": "old_lon"}).copy()
    old["candidate_nodeid"] = "CWB" + old.old_nodeid
    joined = old.merge(stops, left_on="candidate_nodeid", right_on="nodeid", how="outer", indicator=True, validate="one_to_one")
    paired = joined[joined._merge == "both"].copy()
    a = np.radians(paired[["old_lat", "old_lon"]].to_numpy(float))
    b = np.radians(paired[["lat", "lon"]].to_numpy(float))
    h = np.sin((a[:, 0] - b[:, 0]) / 2) ** 2 + np.cos(a[:, 0]) * np.cos(b[:, 0]) * np.sin((a[:, 1] - b[:, 1]) / 2) ** 2
    paired["coordinate_delta_m"] = 2 * 6371008.8 * np.arcsin(np.sqrt(np.clip(h, 0, 1)))
    paired["same_name"] = paired.old_name == paired.nodenm
    counts = joined._merge.value_counts()
    report = {"old_rows": len(old), "current_rows": len(stops),
              "old_reference_date": "2025-12-31", "current_collection_date_utc": "2026-10-16",
              "id_candidate_rule": "CWB + old nine-digit ID; empirically audited, not provider-certified",
              "matched_id_candidates": int(counts.get("both", 0)), "old_only_ids": int(counts.get("left_only", 0)),
              "current_only_ids": int(counts.get("right_only", 0)), "same_name_matched": int(paired.same_name.sum()),
              "matched_coordinate_delta_m": paired.coordinate_delta_m.describe(percentiles=[.5, .95]).to_dict(),
              "matched_delta_over_1m": int((paired.coordinate_delta_m > 1).sum()),
              "old_virtual_name_rows": int(old.old_name.str.contains("가상", na=False).sum()),
              "current_virtual_name_rows": int(stops.nodenm.str.contains("가상", na=False).sum()),
              "old_authority_counts": old["관할관청"].fillna("missing").value_counts().to_dict(),
              "interpretation": "Different snapshot, ID systems and provider scope; unmatched IDs do not establish stop closure."}
    return report, paired[["old_nodeid", "nodeid", "old_name", "nodenm", "coordinate_delta_m", "same_name"]]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def boundary_value(values: pd.Series, share: float, lower_is_worse: bool) -> float | None:
    known = pd.to_numeric(values, errors="coerce").dropna()
    if known.nunique() <= 1:
        return None
    n = max(1, int(np.ceil(len(known) * share)))
    return float((known.nsmallest(n) if lower_is_worse else known.nlargest(n)).iloc[-1])


def flags_for(indicators: pd.DataFrame, share: float, ready: bool) -> pd.DataFrame:
    """A failed gate leaves every v2 flag unknown; partial domains never classify."""
    flags = classify(indicators, share)
    if ready:
        return flags
    return pd.DataFrame(pd.NA, index=flags.index, columns=flags.columns, dtype="boolean")


def group_labels(flag: pd.Series) -> pd.Series:
    flag = flag.astype("boolean")
    group = pd.Series("미확정", index=flag.index)
    group[flag.fillna(False).to_numpy(bool)] = "취약"
    group[(~flag).fillna(False).to_numpy(bool)] = "비취약"
    return group


def summarize(table: pd.DataFrame, sets: dict, city_rentals: int) -> pd.DataFrame:
    """Counts with station and 2024-rental shares; never absolute counts alone."""
    rows = []
    for label, column in sets.items():
        group = group_labels(table[column])
        group[~table.classified] = "판정 제외(운영센터)"
        for district in (*DISTRICTS, "전체"):
            part = table if district == "전체" else table[table.district == district]
            for name in ("취약", "비취약", "미확정", "판정 제외(운영센터)"):
                sel = part[group[part.index] == name]
                if name not in ("취약", "비취약") and sel.empty:
                    continue
                rentals = int(sel.rentals_2024.sum())
                rows.append({"set": label, "flag_column": column, "district": district, "group": name,
                             "stations": len(sel), "station_share_in_district": len(sel) / len(part),
                             "active_2024_stations": int(sel.active_2024.sum()), "rentals_2024": rentals,
                             "rental_share_in_district_2024": rentals / int(part.rentals_2024.sum()),
                             "rental_share_of_city_2024": rentals / city_rentals})
    return pd.DataFrame(rows)


def compare_to_main(table: pd.DataFrame, column: str) -> dict:
    a = table.vulnerable.astype(object).where(table.vulnerable.notna(), "NA")
    b = table[column].astype(object).where(table[column].notna(), "NA")
    return {"same": int((a == b).sum()), "true_to_false": int(((a == True) & (b == False)).sum()),  # noqa: E712
            "false_to_true": int(((a == False) & (b == True)).sum()),  # noqa: E712
            "known_unknown_changes": int(((a == "NA") ^ (b == "NA")).sum())}


def render_map(table: pd.DataFrame, stops: pd.DataFrame, out_base: Path, font: Path) -> dict:
    """Review map: stations by main-flag class. No local district polygons exist, so none are drawn."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    from matplotlib.lines import Line2D
    font_manager.fontManager.addfont(font)
    plt.rcParams.update({"font.family": font_manager.FontProperties(fname=font).get_name(), "font.size": 8.5,
                         "axes.unicode_minus": False, "svg.fonttype": "path", "svg.hashsalt": VULN_DEFINITION_ID})
    ink, ink2 = "#0b0b0b", "#52514e"
    c = table[table.classified]
    bus, fac = c.bus_poor.astype(bool), c.facility_poor.astype(bool)
    groups = [("복합 취약(버스·생활시설)", c[bus & fac], "#eb6834", "D", 26, 6),
              ("버스만 취약", c[bus & ~fac], "#2a78d6", "s", 20, 5),
              ("생활시설만 취약", c[~bus & fac], "#1baf7a", "^", 26, 5),
              ("비취약", c[~bus & ~fac], "#c3c2b7", "o", 8, 4)]
    ops = table[~table.classified]
    fig = plt.figure(figsize=(178 / 25.4, 205 / 25.4), facecolor="white")
    ax = fig.add_axes([0.02, 0.19, 0.96, 0.70])
    ax.scatter(pd.to_numeric(stops.lon), pd.to_numeric(stops.lat), s=0.6, c="#e1e0d9", linewidths=0, zorder=1)
    handles = [Line2D([], [], ls="", marker="o", ms=2.5, color="#e1e0d9", label="현재 버스 정류소(참고)")]
    for label, part, color, marker, size, z in groups:
        ax.scatter(part.lon, part.lat, s=size, c=color, marker=marker, edgecolors="white", linewidths=0.4, zorder=z)
        handles.append(Line2D([], [], ls="", marker=marker, ms=6, color=color, markeredgecolor="white",
                              label=f"{label} {len(part)}곳"))
    ax.scatter(ops.lon, ops.lat, s=34, facecolors="none", edgecolors=ink, linewidths=0.9, zorder=7)
    handles.append(Line2D([], [], ls="", marker="o", ms=6, markerfacecolor="none", markeredgecolor=ink,
                          label=f"판정 제외(운영센터) {len(ops)}곳"))
    # Label offsets (degrees) only move names off dense clusters; they mark no boundary.
    offsets = {"의창구": (0, .03), "성산구": (.06, 0), "마산회원구": (-.04, .005), "마산합포구": (-.04, 0), "진해구": (0, .025)}
    for district, part in table.groupby("district"):
        dx, dy = offsets.get(district, (0, 0))
        ax.text(part.lon.median() + dx, part.lat.median() + dy, district, fontsize=10, color=ink2, ha="center",
                va="center", zorder=8)
    ax.set_aspect(1 / np.cos(np.radians(35.2)))
    ax.set_axis_off()
    x0, x1 = ax.get_xlim()
    y0, y1 = ax.get_ylim()
    km5 = 5 / (111.195080 * np.cos(np.radians(35.2)))  # 5 km in degrees of longitude at 35.2N
    bx, by = x0 + (x1 - x0) * 0.04, y0 + (y1 - y0) * 0.03
    ax.plot([bx, bx + km5], [by, by], color=ink, lw=1.5, solid_capstyle="butt")
    ax.text(bx + km5 / 2, by + (y1 - y0) * 0.012, "5 km · 위쪽이 북쪽", ha="center", fontsize=8, color=ink)
    ax.legend(handles=handles, loc="upper right", frameon=False, fontsize=8.5, handletextpad=0.3, borderaxespad=0.2)
    share = round(RULE["main_share"] * 100)
    fig.text(0.03, 0.965, f"누비자 거점 접근성 취약 판정(사전 고정 규칙 v2, 하위 {share}% 기준)", fontsize=12.5, color=ink,
             va="top")
    fig.text(0.03, 0.925, f"판정 대상 {len(c)}곳 중 취약 {int((bus | fac).sum())}곳, 이 중 버스·생활시설 복합 취약 "
             f"{int((bus & fac).sum())}곳", fontsize=9.5, color=ink2, va="top")
    notes = [f"버스 취약: 반경 {RULE['bus_radius_m']}m 안 정류소를 지나는 노선의 시간당 운행횟수 합이 하위 {share}%",
             f"생활시설 취약: 일상 의료·약국·전통시장까지 직선거리 중 {RULE['facility_poor_min_flags']}개 이상이 상위 {share}%"
             " · 취약 = 둘 중 하나 이상",
             "시점: 거점 2024·2025년 운영 이력, 정류소·노선 2026-10-16 수집(현재망), 시간표 2025-11-15,"
             " 병의원·약국 2024.12, 전통시장 2025-11-10",
             "한계: 직선거리(보행경로 아님), 과거 버스망 소급 불가, 시설 운영시간·시간대별 버스 미반영, 거점 위치 기준(주민 취약도 아님)",
             "구 경계: 로컬 경계 자료 없음, 구 이름은 해당 구 거점 위치의 중앙값 부근 빈 곳에 표기(경계 표시 아님)",
             "자료: 창원시 누비자 터미널 현황, 국가대중교통정보센터, 창원시 시내버스 운행시간표, 건강보험심사평가원 병의원·약국 현황,"
             " 전국전통시장표준데이터"]
    for i, note in enumerate(notes):
        fig.text(0.03, 0.175 - i * 0.026, note, fontsize=7.6, color=ink if i < 2 else ink2, va="top")
    png, svg = out_base.with_suffix(".png"), out_base.with_suffix(".svg")
    out_base.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(png, dpi=300, facecolor="white", metadata={"Software": None})
    fig.savefig(svg, facecolor="white", metadata={"Date": None})
    plt.close(fig)
    root = out_base.parents[2]
    return {"files": {p.relative_to(root).as_posix(): sha256(p) for p in (png, svg)},
            "counts": {label: len(part) for label, part, *_ in groups} | {"판정 제외(운영센터)": len(ops)},
            "district_boundaries": "not drawn: no local boundary file", "font": font.relative_to(root).as_posix()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--write-lock", action="store_true", help="Write the v2 rule lock once; never overwrites")
    args = parser.parse_args()
    root = args.root.resolve()
    outdir = root / "data/processed/accessibility_scenarios"
    outdir.mkdir(parents=True, exist_ok=True)
    doc_path = root / "data/metadata/accessibility_scenarios.md"
    lock_path = outdir / "vulnerability_lock.json"
    doc_text = doc_path.read_text(encoding="utf-8")
    if args.write_lock:
        if lock_path.exists():
            raise SystemExit(f"{lock_path} exists; a lock is never overwritten. Use a new definition ID instead.")
        lock = {"definition_id": VULN_DEFINITION_ID, "rule": RULE, "rule_sha256": canonical_sha256(RULE),
                "doc_path": doc_path.relative_to(root).as_posix(),
                "doc_rule_section_sha256": rule_section_sha256(doc_text),
                "locked_at_utc": datetime.now(timezone.utc).isoformat(), "policy_results_seen": False}
        lock_path.write_text(json.dumps(lock, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({k: lock[k] for k in ("definition_id", "rule_sha256", "doc_rule_section_sha256",
                                               "locked_at_utc")}))
        return
    if not lock_path.exists():
        raise SystemExit("vulnerability lock missing; write it with --write-lock before producing flags")
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    problems = verify_lock(lock, doc_text)
    if problems:
        raise SystemExit("vulnerability lock mismatch: " + "; ".join(problems))

    derived = root / "data/raw/approved_public_apis" / API_RUN / "derived_csv"
    station_path = root / "data/raw/nubija_stations/nubija_stations_2023_2025.xlsx"
    stop_path, route_path = derived / "changwon_stops.csv", derived / "changwon_all_route_stops.csv"
    catalogue_path = derived / "changwon_routes.csv"
    old_path = root / "data/raw/transit/bus_stops_15037805_0.csv"
    timetable_path = root / "data/raw/transit/bus_timetable_15152427_0.csv"
    panel_path = root / "data/processed/event_panel/hourly_panel_2024.parquet"
    stations, station_qa = load_stations(station_path)
    stops = pd.read_csv(stop_path, dtype=str).rename(columns={"gpslati": "lat", "gpslong": "lon"})
    routes = pd.read_csv(route_path, dtype=str).rename(columns={"gpslati": "lat", "gpslong": "lon"})
    for data in (stops, routes):
        data["reference_date"] = "2026-10-16"  # collection date; API has no historical effective date
    markets = load_markets(root)
    hira, hira_qa = load_hira(root, "2024-12")
    hira_alt, hira_alt_qa = load_hira(root, "2025-12")
    facilities = pd.concat([hira, markets], ignore_index=True)
    facilities_alt = pd.concat([hira_alt, markets], ignore_index=True)
    gate_columns = ["station_id", "district", "lat", "lon", "reference_date"]
    scenario, status = build_accessibility(stations[gate_columns], stops, routes, facilities)
    scenario_alt, status_alt = build_accessibility(stations[gate_columns], stops, routes, facilities_alt)
    catalogue = pd.read_csv(catalogue_path, dtype=str)
    status["route_catalogue_quality"] = {
        "rows": len(catalogue), "unique_route_ids": int(catalogue.routeid.nunique()),
        "duplicate_route_ids": int(catalogue.routeid.duplicated().sum()),
        "missing_route_ids": int(catalogue.routeid.isna().sum()),
        "catalogue_without_route_stops": sorted(set(catalogue.routeid) - set(routes.routeid)),
        "route_stops_without_catalogue": sorted(set(routes.routeid) - set(catalogue.routeid)),
        "requested_returned_routeid_mismatches": int((routes.requested_routeid != routes.routeid).sum()),
    }
    if any(status["route_catalogue_quality"][k] for k in (
            "duplicate_route_ids", "missing_route_ids", "catalogue_without_route_stops",
            "route_stops_without_catalogue", "requested_returned_routeid_mismatches")):
        for s in (status, status_alt):
            s["ready"] = False
            s["missing_inputs"].append("route catalogue consistency failed")

    rate_table, rate_qa = route_rates(pd.read_csv(timetable_path, dtype=str, encoding="utf-8-sig"), catalogue)
    rentals = pd.read_parquet(panel_path, columns=["station_id", "departures"]).groupby("station_id").departures.sum()
    city_rentals = int(rentals.sum())
    table = stations.drop(columns="reference_date").assign(coordinate_reference_date=stations.reference_date)
    table["rentals_2024"] = table.station_id.map(rentals).astype("Int64")
    table["nearest_stop_m"] = scenario.nearest_stop_m
    table = table.join(bus_indicators(stations, stops, routes, rate_table.set_index("routeid").rate))
    table["bus_trips_per_hour_300m_upper"] = (table.bus_trips_per_hour_300m
                                              + table.bus_routes_unmatched_300m * rate_qa["max_matched_rate"])
    table["nearest_primary_care_m"] = scenario.nearest_medical_m
    table["nearest_pharmacy_m"] = scenario.nearest_pharmacy_m
    table["nearest_traditional_market_m"] = scenario.nearest_grocery_m
    table["nearest_primary_care_m_2025_12"] = scenario_alt.nearest_medical_m
    table["nearest_pharmacy_m_2025_12"] = scenario_alt.nearest_pharmacy_m
    # Operating centers come from the parent's station reference; elevation is a reference column only.
    reference_path = root / "data/processed/bike_chains/stations.csv"
    reference = pd.read_csv(reference_path, dtype=str, encoding="utf-8-sig")
    if reference.station_id.duplicated().any():
        raise SystemExit("bike_chains/stations.csv has duplicate station_id; operating-center join is ambiguous")
    reference = reference.set_index("station_id")
    table["is_ops_center"] = table.station_id.map(
        reference.is_ops_center.str.lower().map({"true": True, "false": False})).astype("boolean")
    table["elev_m"] = table.station_id.map(pd.to_numeric(reference.elev_m, errors="coerce"))
    table["classified"] = table.is_ops_center.eq(False).fillna(False).astype(bool)
    matched_ref = table.station_id.isin(reference.index)
    ref_xy = reference.loc[table.station_id[matched_ref], ["lat", "lon"]].astype(float).set_axis(table.index[matched_ref])
    ref_shift = np.diagonal(distances_m(table.loc[matched_ref, ["lat", "lon"]], ref_xy)) if matched_ref.any() else np.array([])

    ready = bool(status["ready"])
    universe = table.classified

    def universe_flags(frame: pd.DataFrame, share: float, ok: bool) -> pd.DataFrame:
        return flags_for(frame[universe], share, ok).reindex(frame.index)

    table = table.join(universe_flags(table, RULE["main_share"], ready))
    for share, tag in ((0.2, "q20"), (0.3, "q30")):
        f = universe_flags(table, share, ready)
        table[f"vulnerable_{tag}"], table[f"vulnerable_both_{tag}"] = f.vulnerable, f.vulnerable_both
    alt = table.assign(nearest_primary_care_m=table.nearest_primary_care_m_2025_12,
                       nearest_pharmacy_m=table.nearest_pharmacy_m_2025_12)
    f = universe_flags(alt, RULE["main_share"], ready and bool(status_alt["ready"]))
    table["vulnerable_hira_2025_12"], table["vulnerable_both_hira_2025_12"] = f.vulnerable, f.vulnerable_both
    f = universe_flags(table.assign(bus_trips_per_hour_300m=table.bus_trips_per_hour_300m_upper), RULE["main_share"], ready)
    table["vulnerable_bus_upper"], table["vulnerable_both_bus_upper"] = f.vulnerable, f.vulnerable_both
    table["definition_id"] = VULN_DEFINITION_ID
    table["bus_network_reference"] = "TAGO collected 2026-10-16 UTC"
    table["timetable_reference"] = "Changwon city bus timetable 2025-11-15"
    table["facility_reference"] = "HIRA 2024-12; traditional markets 2025-11-10"
    classification_ready = (ready and bool(table.is_ops_center.notna().all())
                            and bool(table.loc[universe, "vulnerable"].notna().all()))

    lower = {"bus_trips_per_hour_300m": True, "nearest_primary_care_m": False, "nearest_pharmacy_m": False,
             "nearest_traditional_market_m": False}
    distribution = []
    for column in (*lower, "bus_stops_300m", "bus_routes_300m", "bus_routes_unmatched_300m", "nearest_stop_m",
                   "bus_trips_per_hour_300m_upper", "nearest_primary_care_m_2025_12", "nearest_pharmacy_m_2025_12",
                   "elev_m"):
        s = pd.to_numeric(table.loc[universe, column], errors="coerce").astype(float)
        row = {"indicator": column, "n": int(s.notna().sum()), "missing": int(s.isna().sum()),
               "min": s.min(), "p10": s.quantile(.1), "p25": s.quantile(.25), "median": s.median(),
               "p75": s.quantile(.75), "p90": s.quantile(.9), "max": s.max(), "mean": s.mean()}
        if column in lower:
            for share in RULE["shares"]:
                tag = f"q{round(share * 100)}"
                row[f"boundary_{tag}"] = boundary_value(s, share, lower[column])
                row[f"flagged_{tag}"] = int(quantile_flag(s, share, lower[column]).sum()) if ready else None
        distribution.append(row)
    sets = {"주 판정 q25": "vulnerable", "복합 취약 q25": "vulnerable_both", "버스 취약 q25": "bus_poor",
            "생활시설 취약 q25": "facility_poor", "주 판정 q20": "vulnerable_q20", "주 판정 q30": "vulnerable_q30",
            "복합 취약 q20": "vulnerable_both_q20", "복합 취약 q30": "vulnerable_both_q30",
            "민감도 HIRA 2025.12": "vulnerable_hira_2025_12", "민감도 버스 미대응 상한": "vulnerable_bus_upper"}
    summary = summarize(table, sets, city_rentals)
    target_rentals = int(table.rentals_2024.sum())

    status.pop("selected_counts", None)  # v1 combined-score counts are not produced for policy use
    status.update({
        "classification_ready": classification_ready, "definition_id": VULN_DEFINITION_ID,
        "superseded_definition": {"definition_id": DEFINITION_ID, "scores_written": False,
                                  "reason": "2026-10-17 instruction: per-indicator quantile flags, no composite score"},
        "station_rows": len(table),
    })
    status["v2"] = {
        "lock": {"path": lock_path.relative_to(root).as_posix(), "verified": True,
                 **{k: lock[k] for k in ("rule_sha256", "doc_rule_section_sha256", "locked_at_utc", "policy_results_seen")}},
        "gate_ready_main_hira_2024_12": ready, "gate_ready_sensitivity_hira_2025_12": bool(status_alt["ready"]),
        "sensitivity_missing_inputs": status_alt["missing_inputs"],
        "sensitivity_coverage_by_district": status_alt["coverage_by_district"],
        "classification_ready": classification_ready,
        "stations": station_qa, "hira_2024_12": hira_qa, "hira_2025_12": hira_alt_qa,
        "markets": {"rows": len(markets), "rows_by_district": markets.district.value_counts(dropna=False).to_dict(),
                    "valid_coordinates": int(valid_coordinates(markets).sum()),
                    "missing_coordinate_names": markets.loc[markets.lat.isna(), "facility_name"].tolist(),
                    "reference_dates": sorted(markets.reference_date.dropna().unique().tolist())},
        "route_rates": rate_qa,
        "universe": {"terminals": len(table), "classified": int(universe.sum()),
                     "operating_centers": table.loc[table.is_ops_center.fillna(False).astype(bool), "station_id"].tolist(),
                     "operating_center_status_unknown": int(table.is_ops_center.isna().sum()),
                     "reference_file": reference_path.relative_to(root).as_posix(),
                     "reference_rows": len(reference), "terminals_missing_in_reference": int((~matched_ref).sum()),
                     "max_coordinate_difference_vs_reference_m": float(ref_shift.max()) if ref_shift.size else None},
        "reference_only_columns": {"elev_m": "bike_chains/stations.csv (Copernicus GLO-30 DSM, 3x3 minimum); not used in flags"},
        "flag_counts": {c: {"true": int(table.loc[universe, c].sum()), "false": int((~table.loc[universe, c]).sum()),
                            "unknown": int(table.loc[universe, c].isna().sum())}
                        for c in table if c.startswith(("flag_", "vulnerable", "bus_poor", "facility_poor"))},
        "sensitivity_vs_main": {c: compare_to_main(table[universe], c) for c in (
            "vulnerable_q20", "vulnerable_q30", "vulnerable_hira_2025_12", "vulnerable_bus_upper")},
        "rentals_2024": {"source": panel_path.relative_to(root).as_posix(), "definition": "sum of departures",
                         "city_total": city_rentals, "target_stations_total": target_rentals,
                         "non_target_total": city_rentals - target_rentals,
                         "target_stations_missing_in_panel": int(table.rentals_2024.isna().sum())},
        "time_points": {"stations": "2024년·2025년 sheets (year-end snapshots)", "bus_network": "TAGO 2026-10-16 UTC",
                        "timetable": "2025-11-15", "medical_pharmacy": "HIRA 2024-12 (sensitivity 2025-12)",
                        "markets": "2025-11-10", "rentals": "2024 calendar year"},
        "public_service": {"available": False,
                           "reason": "no local official coordinate source for 행정복지센터 or other public offices"},
        "grocery_full_coverage": False,
        "not_measured": ["walking network distance", "historical bus network 2024-2025",
                         "operating hours of facilities and hour-of-day bus service", "residents outside stations"],
    }
    status["v2"]["map"] = render_map(table, stops, root / "outputs/accessibility_audit/vulnerability_map",
                                     root / "assets/fonts/NotoSansKR.ttf")
    status["generated_at_utc"] = datetime.now(timezone.utc).isoformat()
    hira_files = [root / HIRA_DIR / f"hira_{k}_changwon5_{s}.csv" for k in ("hosp", "pharm") for s in ("2024-12", "2025-12")]
    status["source_files"] = {p.relative_to(root).as_posix(): sha256(p) for p in (
        station_path, stop_path, route_path, catalogue_path, old_path, timetable_path, panel_path, reference_path,
        root / "data/raw/accessibility_facilities" / MARKET_FILE, *hira_files, lock_path)}
    status["facility_file_inventory"] = [{"path": p.relative_to(root).as_posix(), "bytes": p.stat().st_size, "sha256": sha256(p)}
                                         for folder in (root / "data/raw/accessibility_facilities", root / "data/processed/accessibility_facilities")
                                         if folder.exists() for p in sorted(folder.rglob("*.csv"))]
    old = pd.read_csv(old_path, dtype=str, encoding="utf-8-sig")
    comparison, crosswalk = compare_old_stops(old, stops)
    status["old_current_comparison"] = comparison

    v1_scores = [c for c in scenario if c.startswith("vulnerable") or c.endswith("component")]
    scenario.drop(columns=v1_scores).to_csv(outdir / "station_accessibility.csv", index=False, encoding="utf-8-sig")
    valid = valid_coordinates(facilities)
    facilities.assign(coordinate_status=np.where(valid, "valid", np.where(
        facilities.lat.isna() & facilities.lon.isna() & facilities.address.fillna("").str.strip().ne(""),
        "excluded_missing_coordinates", "invalid"))).to_csv(outdir / "facility_evidence.csv", index=False, encoding="utf-8-sig")
    crosswalk.to_csv(outdir / "old_current_stop_id_candidates.csv", index=False, encoding="utf-8-sig")
    labels = {"medical": "일상 의료", "pharmacy": "약국", "grocery": "전통시장(장보기 전체 아님)"}
    pd.DataFrame([{"district": d, "category": c, "category_label": labels[c], **status["coverage_by_district"][d][c]}
                  for d in DISTRICTS for c in CATEGORIES]).to_csv(
        outdir / "facility_coverage_by_district.csv", index=False, encoding="utf-8-sig")
    scenario.groupby("district").agg(stations=("station_id", "size"), nearest_stop_median_m=("nearest_stop_m", "median"),
                                     nearest_stop_max_m=("nearest_stop_m", "max")).to_csv(
        outdir / "district_bus_diagnostics.csv", encoding="utf-8-sig")
    rate_table.to_csv(outdir / "bus_route_timetable_match.csv", index=False, encoding="utf-8-sig")
    table.to_parquet(outdir / "station_vulnerability.parquet", index=False)
    table.to_csv(outdir / "station_vulnerability.csv", index=False, encoding="utf-8-sig")
    summary.to_csv(outdir / "vulnerability_summary.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(distribution).to_csv(outdir / "vulnerability_indicator_distribution.csv", index=False, encoding="utf-8-sig")
    (outdir / "status.json").write_text(json.dumps(status, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({"ready": status["ready"], "classification_ready": classification_ready,
                      "stations": len(table), "missing_input_groups": len(status["missing_inputs"]),
                      "vulnerable": status["v2"]["flag_counts"]["vulnerable"],
                      "vulnerable_both": status["v2"]["flag_counts"]["vulnerable_both"],
                      "output": str(outdir)}, ensure_ascii=False))


if __name__ == "__main__":
    main()


