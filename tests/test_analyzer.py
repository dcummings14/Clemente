from __future__ import annotations

import unittest
from pathlib import Path

from milk_quality_agent.analyzer import analyze_rows, load_quality_csv, parse_quality_csv
from milk_quality_agent.history import RunHistory


SAMPLE_CSV = Path(
    r"C:\Users\DavidCummings\OneDrive - Cobblestone Milk Cooperative\Cobblestone\CS Reporting\Quality Reports\2026\04Sett1.csv"
)

THRESHOLDS = {
    "BF": {"low_warning": 3.5, "drop_warning": 0.3},
    "SCC": {"warning": 300, "serious": 400},
    "SPC": {"warning": 10, "serious": 20},
    "PIC": {"warning": 10, "serious": 25},
    "LPC": {"warning": 50, "serious": 100},
}


class AnalyzerTests(unittest.TestCase):
    def test_sample_csv_schema_loads(self) -> None:
        if not SAMPLE_CSV.exists():
            self.skipTest("Representative 04Sett1.csv is not available on this machine.")
        rows = load_quality_csv(SAMPLE_CSV)
        self.assertEqual(len(rows), 896)
        self.assertEqual(rows[0].producer_id, "1009")
        self.assertIn("PIC", rows[0].metrics)

    def test_blank_metrics_are_none_not_zero(self) -> None:
        rows = parse_quality_csv(
            "PICKUPDATE,TESTDATE,PRODDIV,PRODNUM,TANK,BARCODE,BF,SCC,SPC,PIC,LPC\n"
            "4/1/2026,4/2/2026,4CS,1009,2,abc,3.8,200,,,,\n"
        )
        self.assertIsNone(rows[0].metrics["SPC"])
        self.assertIsNone(rows[0].metrics["PIC"])
        self.assertIsNone(rows[0].metrics["LPC"])
        self.assertEqual(analyze_rows(rows, THRESHOLDS).issues, [])

    def test_threshold_classification(self) -> None:
        rows = parse_quality_csv(
            "PICKUPDATE,TESTDATE,PRODDIV,PRODNUM,TANK,BARCODE,BF,SCC,SPC,PIC,LPC\n"
            "4/1/2026,4/2/2026,4CS,1009,2,a,3.9,299,9,9,49\n"
            "4/2/2026,4/3/2026,4CS,1009,2,b,3.4,300,10,10,50\n"
            "4/3/2026,4/4/2026,4CS,1009,2,c,3.0,400,20,25,100\n"
        )
        result = analyze_rows(rows, THRESHOLDS)
        by_metric = {(issue.metric, issue.issue_type, issue.severity) for issue in result.issues}
        self.assertIn(("BF", "low", "warning"), by_metric)
        self.assertIn(("BF", "drop", "warning"), by_metric)
        self.assertIn(("SCC", "high", "warning"), by_metric)
        self.assertIn(("SCC", "high", "serious"), by_metric)
        self.assertIn(("SPC", "high", "serious"), by_metric)
        self.assertIn(("PIC", "high", "serious"), by_metric)
        self.assertIn(("LPC", "high", "serious"), by_metric)

    def test_duplicate_history_filtering(self) -> None:
        rows = parse_quality_csv(
            "PICKUPDATE,TESTDATE,PRODDIV,PRODNUM,TANK,BARCODE,BF,SCC,SPC,PIC,LPC\n"
            "4/1/2026,4/2/2026,4CS,1009,2,a,3.4,300,,,\n"
        )
        issues = analyze_rows(rows, THRESHOLDS).issues
        history = RunHistory(Path("ignored.json"))
        self.assertEqual(len(history.filter_new(issues)), len(issues))
        history.mark_processed(issues)
        self.assertEqual(history.filter_new(issues), [])


if __name__ == "__main__":
    unittest.main()

