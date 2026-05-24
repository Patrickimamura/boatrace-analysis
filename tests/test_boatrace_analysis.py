import datetime as dt
import tempfile
import unittest
from pathlib import Path
import pandas as pd
import boatrace_analysis as ba

class TestBoatraceAnalysis(unittest.TestCase):
    def test_parse_combination_hyphen(self):
        self.assertEqual(ba.parse_combination("1-2-3"), [1, 2, 3])
    def test_parse_combination_plain(self):
        self.assertEqual(ba.parse_combination("456"), [4, 5, 6])
    def test_normalize_exhibition_time(self):
        self.assertEqual(ba.normalize_exhibition_time(683), 6.83)
        self.assertEqual(ba.normalize_exhibition_time("6.79"), 6.79)
        self.assertIsNone(ba.normalize_exhibition_time(None))
    def test_get_trifecta_payout(self):
        race = {"payouts": {"trifecta": [{"combination": "2-5-3", "amount": "54,160"}]}}
        self.assertEqual(ba.get_trifecta_payout(race), ("2-5-3", 54160))
    def test_should_fetch_remote_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertTrue(ba.should_fetch_remote(dt.date(2026,5,1), Path(tmp)/"missing.json", force_refresh_all=False, refresh_cutoff_date=dt.date(2026,5,10)))
    def test_should_fetch_remote_old_cached(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/"old.json"; p.write_text("[]", encoding="utf-8")
            self.assertFalse(ba.should_fetch_remote(dt.date(2026,5,1), p, force_refresh_all=False, refresh_cutoff_date=dt.date(2026,5,10)))
    def test_should_fetch_remote_recent_cached(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/"recent.json"; p.write_text("[]", encoding="utf-8")
            self.assertTrue(ba.should_fetch_remote(dt.date(2026,5,12), p, force_refresh_all=False, refresh_cutoff_date=dt.date(2026,5,10)))
    def test_should_fetch_remote_force_all(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/"old.json"; p.write_text("[]", encoding="utf-8")
            self.assertTrue(ba.should_fetch_remote(dt.date(2026,5,1), p, force_refresh_all=True, refresh_cutoff_date=dt.date(2026,5,10)))
    def test_write_json_if_changed(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/"x.json"
            self.assertTrue(ba.write_json_if_changed(p, [{"a":1}]))
            self.assertFalse(ba.write_json_if_changed(p, [{"a":1}]))
            self.assertTrue(ba.write_json_if_changed(p, [{"a":2}]))
    def test_make_flat_row(self):
        rr = {"date":"2026-05-23","stadium_number":1,"number":11,"boats":[
            {"racer_boat_number":2,"racer_course_number":2,"racer_start_timing":0.11,"racer_place_number":1,"racer_number":1002,"racer_name":"選手2"},
            {"racer_boat_number":5,"racer_course_number":5,"racer_start_timing":0.13,"racer_place_number":2,"racer_number":1005,"racer_name":"選手5"},
            {"racer_boat_number":3,"racer_course_number":3,"racer_start_timing":0.16,"racer_place_number":3,"racer_number":1003,"racer_name":"選手3"}],
            "payouts":{"trifecta":[{"combination":"2-5-3","amount":54160}]}}
        pr = {"date":"2026-05-23","stadium_number":1,"number":11,"closed_at":"20:00","boats":[
            {"racer_boat_number":2,"racer_number":1002,"racer_name":"選手2","racer_class_number":1,"racer_age":35,"racer_weight":52.0,"racer_average_start_timing":0.14,"racer_assigned_motor_top_2_percent":40.0,"racer_assigned_motor_top_3_percent":55.0},
            {"racer_boat_number":5,"racer_number":1005,"racer_name":"選手5","racer_class_number":2,"racer_age":29,"racer_weight":53.0,"racer_average_start_timing":0.15},
            {"racer_boat_number":3,"racer_number":1003,"racer_name":"選手3","racer_class_number":3,"racer_age":41,"racer_weight":54.0,"racer_average_start_timing":0.17}]}
        vr = {"date":"2026-05-23","stadium_number":1,"number":11,"boats":[{"racer_boat_number":2,"racer_course_number":2,"racer_start_timing":0.05,"racer_exhibition_time":682,"racer_tilt_adjustment":"0.0"}]}
        row = ba.make_flat_row(rr, pr, vr, 5100)
        self.assertTrue(row["is_high_payout"])
        self.assertEqual(row["boat_order"], "2-5-3")
        self.assertEqual(row["course_order_result"], "2-5-3")
        self.assertEqual(row["place1_class_label_est"], "A1")
        self.assertEqual(row["place1_exhibition_time"], 6.82)
    def test_summarize(self):
        df = pd.DataFrame([
            {"is_high_payout": True, "boat_order":"2-5-3", "course_order_result":"2-5-3", "trifecta_payout":54160, "net_profit_100yen":54060, "place1_boat_no":2, "place1_class_label_est":"A1", "place1_motor_top2":40.0, "place1_motor_top3":55.0, "place1_average_start_timing":0.14, "place1_age":35, "place1_weight_program":52.0, "stadium_number":1, "stadium_name":"桐生"},
            {"is_high_payout": False, "boat_order":"1-2-3", "course_order_result":"1-2-3", "trifecta_payout":1200, "net_profit_100yen":1100, "place1_boat_no":1, "place1_class_label_est":"A1", "place1_motor_top2":30.0, "place1_motor_top3":45.0, "place1_average_start_timing":0.15, "place1_age":40, "place1_weight_program":52.0, "stadium_number":1, "stadium_name":"桐生"}])
        summaries = ba.summarize(df)
        self.assertIn("pattern_by_boat_order", summaries)
        self.assertEqual(summaries["pattern_by_boat_order"].iloc[0]["boat_order"], "2-5-3")

if __name__ == "__main__":
    unittest.main()
