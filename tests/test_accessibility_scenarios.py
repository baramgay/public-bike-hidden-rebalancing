"""Readiness, directional connectivity and tie rules for current accessibility."""
from pathlib import Path
import importlib.util
import tempfile
import unittest

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/analysis/build_accessibility_scenarios.py"
if SCRIPT.exists():
    spec = importlib.util.spec_from_file_location("accessibility_scenarios", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
else:
    module = None

DISTRICTS = ("의창구", "성산구", "마산합포구", "마산회원구", "진해구")


def fixture():
    stations = pd.DataFrame([
        {"station_id": str(i), "district": district, "lat": 35.15 + i * .02,
         "lon": 128.6, "reference_date": "2025-12-31"}
        for i, district in enumerate(DISTRICTS)
    ])
    stops = stations.rename(columns={"station_id": "nodeid"}).copy()
    stops["nodeid"] = "N" + stops.nodeid
    stops["reference_date"] = "2026-10-16"
    routes = pd.DataFrame([
        {"routeid": "R", "nodeid": "N" + str(i), "nodeord": i + 1,
         "updowncd": "0", "reference_date": "2026-10-16"}
        for i in range(5)
    ])
    facilities = pd.DataFrame([
        {"facility_id": category + str(i), "district": district,
         "category": category, "lat": 35.15 + i * .02, "lon": 128.601,
         "reference_date": "2026-06-30", "source_url": "https://example.org/official",
         "rights": "public-attribution", "coverage_complete": True,
         "functional_verified": True, "category_definition": category + "_v1"}
        for i, district in enumerate(DISTRICTS)
        for category in ("medical", "pharmacy", "grocery")
    ])
    return stations, stops, routes, facilities


class AccessibilityTests(unittest.TestCase):
    def build(self, *args):
        self.assertIsNotNone(module, "build_accessibility_scenarios.py is not implemented")
        return module.build_accessibility(*args)

    def test_missing_jinhae_medical_blocks_combined_definition(self):
        s, b, r, f = fixture()
        f = f[~((f.district == "진해구") & (f.category == "medical"))]
        out, status = self.build(s, b, r, f)
        self.assertFalse(status["ready"])
        self.assertEqual(status["coverage_by_district"]["진해구"]["medical"]["rows"], 0)
        self.assertTrue(out.vulnerable.isna().all())
        self.assertTrue(out.facility_component.isna().all())
        self.assertTrue(out.nearest_stop_m.notna().all())

    def test_two_district_pharmacy_is_not_five_district_coverage(self):
        s, b, r, f = fixture()
        f = f[(f.category != "pharmacy") | f.district.isin(DISTRICTS[:2])]
        _, status = self.build(s, b, r, f)
        self.assertFalse(status["ready"])
        self.assertTrue(any("pharmacy" in m for m in status["missing_inputs"]))

    def test_missing_coordinates_are_unknown_not_zero_facilities(self):
        s, b, r, f = fixture()
        f.loc[0, "lat"] = np.nan
        out, status = self.build(s, b, r, f)
        self.assertFalse(status["ready"])
        self.assertTrue(out.nearest_medical_m.isna().all())
        self.assertTrue(out.facility_component.isna().all())
        self.assertEqual(status["coverage_by_district"]["의창구"]["medical"]["invalid_coordinates"], 1)

    def test_all_tied_scores_do_not_select_by_station_id(self):
        s, b, r, f = fixture()
        for df in (s, b, f):
            df["lat"], df["lon"] = 35.2, 128.6
        out, status = self.build(s, b, r, f)
        self.assertTrue(status["ready"])
        self.assertFalse(status["classification_ready"])
        self.assertTrue(out.vulnerable.isna().all())
        self.assertEqual(out.combined_component.nunique(), 1)

    def test_ready_fixture_has_directional_destinations_and_rank_sensitivities(self):
        s, b, r, f = fixture()
        # Only the final stop has usable egress to each category. Other districts
        # retain complete facilities far from this route, not missing rows.
        f.loc[f.district != "진해구", "lon"] = 128.8
        out, status = self.build(s, b, r, f)
        self.assertTrue(status["ready"])
        self.assertEqual(out.iloc[0].bus_destination_categories, 3)
        self.assertEqual(out.iloc[-1].bus_destination_categories, 0)
        for col in ("station_id", "reference_date", "bus_component", "facility_component",
                    "vulnerable", "definition_id", "vulnerable_20", "vulnerable_30"):
            self.assertIn(col, out)
        self.assertTrue(out.bus_component.between(0, 1).all())
        self.assertTrue(out.facility_component.between(0, 1).all())
        self.assertEqual(set(out.reference_date), {"2026-10-16"})
        pd.testing.assert_frame_equal(out, self.build(s, b, r.sample(frac=1, random_state=3), f)[0])

    def test_unknown_rights_function_and_false_coverage_cannot_pass_gate(self):
        for column, value in (("rights", "unknown"), ("functional_verified", False),
                              ("coverage_complete", False), ("reference_date", "")):
            s, b, r, f = fixture()
            f.loc[0, column] = value
            with self.subTest(column=column):
                out, status = self.build(s, b, r, f)
                self.assertFalse(status["ready"])
                self.assertTrue(out.vulnerable.isna().all())

    def test_mixed_category_definition_and_reference_date_block_gate(self):
        for column, value in (("category_definition", "different"),
                              ("reference_date", "2026-05-31")):
            s, b, r, f = fixture()
            f.loc[0, column] = value
            with self.subTest(column=column):
                self.assertFalse(self.build(s, b, r, f)[1]["ready"])

    def test_invalid_station_coordinates_and_route_orders_block_gate(self):
        s, b, r, f = fixture()
        s.loc[0, "lat"] = 128.6
        self.assertFalse(self.build(s, b, r, f)[1]["ready"])
        s, b, r, f = fixture()
        r.loc[1, "nodeord"] = 1
        self.assertFalse(self.build(s, b, r, f)[1]["ready"])

    def test_ties_at_quantile_boundary_are_kept_together(self):
        self.assertIsNotNone(module, "tie-preserving classification is not implemented")
        scores = pd.Series([.1, .2, .9, .9])
        result = module.select_vulnerable(scores, .25)
        self.assertEqual(result.tolist(), [False, False, True, True])

    def test_tago_qa_counts_repeated_visits_without_join_explosion(self):
        self.assertIsNotNone(module, "TAGO QA is not implemented")
        s, b, r, _ = fixture()
        b["nodenm"] = ["가상" if i == 0 else "stop" for i in range(5)]
        b["nodeno"] = ["1", "1", "2", "3", "4"]
        r = pd.concat([r, r.iloc[[0]].assign(nodeord=6)], ignore_index=True)
        q = module.transit_quality(b, r)
        self.assertEqual(q["duplicate_route_direction_order"], 0)
        self.assertEqual(q["repeat_route_node_visits"], 1)
        self.assertEqual(q["joined_rows"], 6)
        self.assertEqual(q["virtual_name_stops"], 1)
        self.assertEqual(q["unknown_stop_ids"], 0)
        self.assertEqual(q["duplicate_nonblank_nodeno"], 1)
        self.assertEqual(q["duplicate_stop_coordinates"], 0)

    def test_local_medical_source_decodes_verified_cp949(self):
        self.assertIsNotNone(module)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            raw = root / "data/raw/accessibility_facilities"
            raw.mkdir(parents=True)
            pd.DataFrame({"의료기관주소(도로명)": ["창원시 의창구 중앙로"]}).to_csv(
                raw / "changwon_uichang_seongsan_medical_20251117.csv",
                index=False, encoding="cp949")
            data, _ = module.load_existing_facilities(root)
            self.assertEqual(data.district.tolist(), ["의창구"])
            self.assertTrue(data.lat.isna().all())

    def test_missing_individual_transit_date_cannot_hide_in_unique_dates(self):
        s, b, r, f = fixture()
        b.loc[0, "reference_date"] = pd.NA
        self.assertFalse(self.build(s, b, r, f)[1]["ready"])

    def test_equivalent_numeric_orders_are_detected_as_duplicate_visits(self):
        s, b, r, f = fixture()
        r["nodeord"] = r.nodeord.astype(str)
        r.loc[1, "nodeord"] = "01"
        self.assertFalse(self.build(s, b, r, f)[1]["ready"])

    def test_distance_units_and_coordinate_order(self):
        self.assertIsNotNone(module)
        a = pd.DataFrame({"lat": [35.2], "lon": [128.6]})
        b = pd.DataFrame({"lat": [35.201], "lon": [128.6]})
        self.assertAlmostEqual(module.distances_m(a, b)[0, 0], 111.1950802335, places=6)
        self.assertFalse(module.valid_coordinates(pd.DataFrame({"lat": [128.6], "lon": [35.2]})).any())

    def test_nonnumeric_route_coordinates_are_diagnostic_failure(self):
        s, b, r, f = fixture()
        r = r.merge(b[["nodeid", "lat", "lon"]], on="nodeid", validate="many_to_one")
        r["lat"] = r.lat.astype(object)
        r.loc[0, "lat"] = "invalid"
        _, status = self.build(s, b, r, f)
        self.assertFalse(status["ready"])
        self.assertEqual(status["transit_quality"]["invalid_route_stop_coordinates"], 1)

    def test_nullable_verification_fields_fail_closed(self):
        for column, check in (("coverage_complete", "complete"),
                              ("functional_verified", "functional_verified")):
            with self.subTest(column=column):
                s, b, r, f = fixture()
                f[column] = f[column].astype("boolean")
                f.loc[0, column] = pd.NA
                out, status = self.build(s, b, r, f)
                self.assertFalse(status["ready"])
                self.assertFalse(status["classification_ready"])
                self.assertFalse(status["coverage_by_district"]["의창구"]["medical"][check])
                self.assertTrue(out.filter(like="vulnerable").isna().all().all())
                self.assertTrue(out.combined_component.isna().all())

    def test_verification_fields_require_actual_booleans(self):
        for column in ("coverage_complete", "functional_verified"):
            for value in (1, 1.0, "True", pd.NA, None, np.nan):
                with self.subTest(column=column, value=value):
                    s, b, r, f = fixture()
                    f[column] = f[column].astype(object)
                    f.loc[0, column] = value
                    out, status = self.build(s, b, r, f)
                    self.assertFalse(status["ready"])
                    self.assertTrue(out.filter(like="vulnerable").isna().all().all())

    def test_nullable_coordinate_mask_has_no_missing_values(self):
        frame = pd.DataFrame({"lat": pd.Series([pd.NA, 35.2, 35.2], dtype="Float64"),
                              "lon": pd.Series([128.6, pd.NA, 128.6], dtype="Float64")})
        mask = module.valid_coordinates(frame)
        self.assertEqual(mask.dtype, bool)
        self.assertFalse(mask.isna().any())
        self.assertEqual(mask.tolist(), [False, False, True])

    def test_nullable_coordinate_missing_is_invalid_in_every_input(self):
        for target in ("station", "stop", "route", "facility"):
            for coordinate in ("lat", "lon"):
                with self.subTest(target=target, coordinate=coordinate):
                    s, b, r, f = fixture()
                    r = r.merge(b[["nodeid", "lat", "lon"]], on="nodeid", validate="many_to_one")
                    frame = {"station": s, "stop": b, "route": r, "facility": f}[target]
                    frame[coordinate] = frame[coordinate].astype("Float64")
                    frame.loc[0, coordinate] = pd.NA
                    out, status = self.build(s, b, r, f)
                    self.assertFalse(status["ready"])
                    self.assertFalse(status["classification_ready"])
                    self.assertTrue(out.filter(like="vulnerable").isna().all().all())
                    self.assertTrue(out.facility_component.isna().all())
                    if target == "facility":
                        check = status["coverage_by_district"]["의창구"]["medical"]
                        self.assertEqual(check["valid_coordinates"], 0)
                        self.assertEqual(check["invalid_coordinates"], 1)
                    elif target == "station":
                        self.assertEqual(status["station_invalid_coordinates"], 1)
                        self.assertEqual(status["station_coordinate_qa_by_district"]["의창구"]["invalid_coordinates"], 1)
                        self.assertTrue(pd.isna(out.loc[0, "nearest_stop_m"]))
                    else:
                        key = "invalid_stop_coordinates" if target == "stop" else "invalid_route_stop_coordinates"
                        self.assertEqual(status["transit_quality"][key], 1)

    def test_complete_nullable_coordinates_and_boolean_flags_remain_ready(self):
        s, b, r, f = fixture()
        for data in (s, b, f):
            data["lat"] = data.lat.astype("Float64")
            data["lon"] = data.lon.astype("Float64")
        for column in ("coverage_complete", "functional_verified"):
            f[column] = f[column].astype("boolean")
        out, status = self.build(s, b, r, f)
        self.assertTrue(status["ready"])
        self.assertTrue(status["classification_ready"])
        self.assertTrue(out.facility_component.notna().all())


def v2_indicators(bus, med, pha, mkt):
    return pd.DataFrame({"bus_trips_per_hour_300m": bus, "nearest_primary_care_m": med,
                         "nearest_pharmacy_m": pha, "nearest_traditional_market_m": mkt}, dtype=float)


class VulnerabilityV2Tests(unittest.TestCase):
    """v2 gate amendment (G4/G4a), quantile boundaries, three-valued combination and lock."""

    def test_gate_stays_false_when_missing_coordinates_have_no_address(self):
        s, b, r, f = fixture()
        f = pd.concat([f, f.iloc[[0]].assign(facility_id="extra", lat=np.nan, lon=np.nan)], ignore_index=True)
        out, status = module.build_accessibility(s, b, r, f)
        self.assertFalse(status["ready"])
        self.assertEqual(status["coverage_by_district"]["의창구"]["medical"]["invalid_coordinates"], 1)
        self.assertTrue(out.nearest_medical_m.isna().all())

    def test_gate_excludes_addressed_missing_coordinates_and_counts_them(self):
        s, b, r, f = fixture()
        f["address"] = "창원시 의창구 주소"
        f = pd.concat([f, f.iloc[[0]].assign(facility_id="extra", lat=np.nan, lon=np.nan)], ignore_index=True)
        out, status = module.build_accessibility(s, b, r, f)
        self.assertTrue(status["ready"])
        cell = status["coverage_by_district"]["의창구"]["medical"]
        self.assertEqual((cell["valid_coordinates"], cell["excluded_missing_coordinates"],
                          cell["invalid_coordinates"]), (1, 1, 0))
        self.assertEqual(status["excluded_missing_coordinate_rows"], 1)
        self.assertTrue(out.nearest_medical_m.notna().all())

    def test_gate_stays_false_when_a_cell_has_only_excluded_rows(self):
        s, b, r, f = fixture()
        f["address"] = "주소"
        f.loc[(f.district == "진해구") & (f.category == "pharmacy"), ["lat", "lon"]] = np.nan
        out, status = module.build_accessibility(s, b, r, f)
        self.assertFalse(status["ready"])
        self.assertEqual(status["coverage_by_district"]["진해구"]["pharmacy"]["valid_coordinates"], 0)
        self.assertTrue(out.nearest_pharmacy_m.isna().all())

    def test_out_of_range_or_one_sided_coordinates_block_even_with_address(self):
        # The cell keeps its valid row, so only the bad extra row can block (G4a cannot mask G4).
        for column, value in (("lat", 128.6), ("lon", np.nan), ("lat", np.nan)):
            with self.subTest(column=column, value=value):
                s, b, r, f = fixture()
                f["address"] = "주소"
                extra = f.iloc[[0]].assign(facility_id="extra")
                extra[column] = value
                status = module.build_accessibility(s, b, r, pd.concat([f, extra], ignore_index=True))[1]
                self.assertFalse(status["ready"])
                self.assertEqual(status["coverage_by_district"]["의창구"]["medical"]["invalid_coordinates"], 1)

    def test_quantile_boundary_uses_ceil_and_keeps_ties(self):
        values = pd.Series([10., 20, 30, 40, 50, 60, 70, 80, 90, 100])
        self.assertEqual(module.quantile_flag(values, .25, False).tolist(), [False] * 7 + [True] * 3)
        self.assertEqual(module.quantile_flag(values, .25, True).tolist(), [True] * 3 + [False] * 7)
        self.assertEqual(int(module.quantile_flag(values, .2, False).sum()), 2)
        self.assertEqual(int(module.quantile_flag(values, .3, False).sum()), 3)
        tied = pd.Series([10., 20, 30, 40, 50, 60, 70, 80, 80, 80])
        self.assertEqual(int(module.quantile_flag(tied, .2, False).sum()), 3)
        self.assertEqual(module.boundary_value(tied, .2, False), 80)
        self.assertTrue(module.quantile_flag(pd.Series([5.] * 4), .25, True).isna().all())

    def test_missing_indicator_is_unknown_not_false(self):
        flags = module.quantile_flag(pd.Series([1., np.nan, 3, 4]), .25, True)
        self.assertTrue(pd.isna(flags[1]))
        self.assertEqual(flags[[0, 2, 3]].tolist(), [True, False, False])

    def test_facility_majority_and_or_and_combination(self):
        ind = v2_indicators(bus=[1, 2, 9, 9, 9, 9, 9, 9], med=[0, 100, 100, 0, 0, 0, 0, 0],
                            pha=[0, 100, 100, 0, 0, 0, 0, 0], mkt=[0, 0, 100, 0, 100, 0, 0, 0])
        out = module.classify(ind, .25)
        self.assertEqual(out.facility_poor.tolist(), [False, True, True] + [False] * 5)
        self.assertEqual(out.vulnerable.tolist(), [True, True, True] + [False] * 5)
        self.assertEqual(out.vulnerable_both.tolist(), [False, True] + [False] * 6)

    def test_unknown_market_flag_propagates_with_three_valued_logic(self):
        ind = v2_indicators(bus=[1, 2, 9, 9, 9, 9, 9, 9], med=[0, 100, 100, 0, 0, 0, 0, 0],
                            pha=[0, 0, 100, 100, 0, 0, 0, 0], mkt=[np.nan] * 8)
        out = module.classify(ind, .25)
        tri = lambda s: ["NA" if pd.isna(x) else bool(x) for x in s]  # noqa: E731
        self.assertEqual(tri(out.facility_poor), [False, "NA", True, "NA", False, False, False, False])
        self.assertEqual(tri(out.vulnerable), [True, True, True, "NA", False, False, False, False])
        self.assertEqual(tri(out.vulnerable_both), [False, "NA", False, False, False, False, False, False])

    def test_failed_gate_leaves_all_v2_flags_unknown(self):
        ind = v2_indicators(bus=[1, 2, 3, 4], med=[1, 2, 3, 4], pha=[1, 2, 3, 4], mkt=[1, 2, 3, 4])
        self.assertTrue(module.flags_for(ind, .25, False).isna().all().all())
        self.assertTrue(module.flags_for(ind, .25, True).vulnerable.notna().all())

    def test_lock_detects_rule_or_document_drift(self):
        import json
        doc = "intro\n" + module.RULE_MARKERS[0] + "\nrule text\n" + module.RULE_MARKERS[1] + "\nresults"
        lock = json.loads(json.dumps({"rule": module.RULE, "rule_sha256": module.canonical_sha256(module.RULE),
                                      "doc_rule_section_sha256": module.rule_section_sha256(doc)}))
        self.assertEqual(module.verify_lock(lock, doc), [])
        self.assertEqual(module.verify_lock(lock, doc.replace("results", "new results")), [])
        self.assertEqual(len(module.verify_lock(lock, doc.replace("rule text", "edited rule"))), 1)
        lock["rule"]["main_share"] = 0.3
        self.assertEqual(len(module.verify_lock(lock, doc)), 1)

    def test_route_rates_match_duplicates_by_origin_and_parse_weekday_trips(self):
        timetable = pd.DataFrame({"노선번호": ["10", "72", "72"], "기점": ["A", "마산역", "진동"],
                                  "종점": ["B", "대현", "대현"], "첫차출발": ["06:00"] * 3, "막차출발": ["22:00"] * 3,
                                  "운행횟수": ["32", "16", "8(토,휴일-6)"], "배차간격(분)": ["30", "60~70", "120"]})
        catalogue = pd.DataFrame({"routeid": ["R10", "R10-1", "R72", "R72-1", "R72-8"],
                                  "routeno": ["10", "10-1", "72", "72-1", "72-8"], "routetp": "x",
                                  "startnodenm": ["A", "A", "마산역종점", "진동환승센터", "마산역종점"],
                                  "endnodenm": ["B", "C", "대현종점", "대현종점", "내추종점"]})
        table, qa = module.route_rates(timetable, catalogue)
        rate = table.set_index("routeid").rate
        self.assertAlmostEqual(rate["R10"], 2.0)
        self.assertAlmostEqual(rate["R72"], 1.0)
        self.assertAlmostEqual(rate["R72-1"], 0.5)
        self.assertTrue(rate[["R10-1", "R72-8"]].isna().all())
        self.assertEqual(qa["matched_routes"], 3)

    def test_bus_indicator_counts_each_route_once_and_unmatched_separately(self):
        station = pd.DataFrame({"lat": [35.2], "lon": [128.6]})
        stops = pd.DataFrame({"nodeid": ["S1", "S2", "S3"], "lat": [35.2, 35.2009, 35.21], "lon": [128.6] * 3})
        route_stops = pd.DataFrame({"routeid": ["A", "A", "B", "C"], "nodeid": ["S1", "S2", "S2", "S3"]})
        out = module.bus_indicators(station, stops, route_stops, pd.Series({"A": 2.0, "B": np.nan, "C": 5.0}))
        self.assertEqual(out.iloc[0].tolist(), [2, 2, 1, 2.0])

    def test_station_union_keeps_operating_years_and_latest_coordinates(self):
        cols = ["터미널번호", "터미널명", "구", "사용유무", "위도", "경도"]
        y24 = pd.DataFrame([["1", "a", "의창구", "사용함", 35.2, 128.6], ["2", "b", "성산구", "사용함", 35.21, 128.61],
                            ["3", "c", "진해구", "사용안함", 35.1, 128.7]], columns=cols)
        y25 = pd.DataFrame([["1", "a", "의창구", "사용함", 35.2, 128.6], ["3", "c", "진해구", "사용함", 35.1, 128.7]],
                           columns=cols)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "stations.xlsx"
            with pd.ExcelWriter(path) as writer:
                y24.to_excel(writer, sheet_name="2024년", index=False)
                y25.to_excel(writer, sheet_name="2025년", index=False)
            stations, qa = module.load_stations(path)
        self.assertEqual(stations.station_id.tolist(), ["1", "2", "3"])
        self.assertEqual(stations.operating_years.tolist(), ["2024;2025", "2024", "2025"])
        self.assertEqual(stations.reference_date.tolist(), ["2025-12-31", "2024-12-31", "2025-12-31"])
        self.assertEqual((qa["only_2024"], qa["only_2025"], qa["both_years"]), (1, 1, 1))


if __name__ == "__main__":
    unittest.main()
