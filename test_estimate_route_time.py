"""estimate_route_time.py のユニットテスト。"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from estimate_route_time import (
    add_estimated_times,
    estimate_route_seconds,
    extract_distance_km,
    format_hhmmss,
    parse_args,
    solve_speed_mps,
)


class TestEstimateRouteTime(unittest.TestCase):
    def test_format_hhmmss(self) -> None:
        self.assertEqual(format_hhmmss(0), "00:00:00")
        self.assertEqual(format_hhmmss(61), "00:01:01")
        self.assertEqual(format_hhmmss(3661), "01:01:01")
        self.assertEqual(format_hhmmss(3661.6), "01:01:02")
        self.assertEqual(format_hhmmss(360000), "100:00:00")
        self.assertEqual(format_hhmmss(-5), "00:00:00")

    def test_extract_distance_km(self) -> None:
        self.assertEqual(
            extract_distance_km({"total_distance_km": 31.4, "distance_km": 28.2, "lead_in_km": 3.2}),
            31.4,
        )
        self.assertEqual(
            extract_distance_km({"distance_km": 28.2, "lead_in_km": 3.2}),
            31.4,
        )
        self.assertEqual(extract_distance_km({}), 0.0)

    def test_physics_monotonicity(self) -> None:
        self.assertEqual(estimate_route_seconds(0.0, 100.0, 200.0, 78.0), 0.0)

        flat_speed_low = solve_speed_mps(150.0, 78.0, 0.0)
        flat_speed_high = solve_speed_mps(250.0, 78.0, 0.0)
        self.assertGreater(flat_speed_high, flat_speed_low)

        flat_time = estimate_route_seconds(20.0, 0.0, 200.0, 78.0)
        hilly_time = estimate_route_seconds(20.0, 500.0, 200.0, 78.0)
        self.assertGreater(hilly_time, flat_time)

    def test_add_estimated_times_and_sorting(self) -> None:
        routes = [
            {"name": "Medium", "total_distance_km": 20.0, "elevation_m": 100},
            {"name": "Short", "total_distance_km": 5.0, "elevation_m": 0},
            {"name": "Long", "total_distance_km": 50.0, "elevation_m": 500},
        ]

        unsorted = add_estimated_times(routes, power_watts=187.5, total_mass_kg=78.0)
        self.assertEqual([r["name"] for r in unsorted], ["Medium", "Short", "Long"])
        self.assertNotIn("estimated_time", routes[0])

        asc = add_estimated_times(routes, power_watts=187.5, total_mass_kg=78.0, sort_order="asc")
        self.assertEqual([r["name"] for r in asc], ["Short", "Medium", "Long"])

        desc = add_estimated_times(
            routes,
            power_watts=187.5,
            total_mass_kg=78.0,
            field="est",
            sort_order="desc",
        )
        self.assertEqual([r["name"] for r in desc], ["Long", "Medium", "Short"])
        self.assertIn("est", desc[0])

    def test_parse_args_validation(self) -> None:
        args = parse_args(["250", "--weight", "65", "--intensity", "80", "--bike-weight", "0", "--sort", "asc"])
        self.assertEqual(args.ftp, 250.0)
        self.assertEqual(args.weight, 65.0)
        self.assertEqual(args.intensity, 80.0)
        self.assertEqual(args.bike_weight, 0.0)
        self.assertEqual(args.sort, "asc")

        for invalid in [["0"], ["-10"], ["nan"], ["inf"], ["abc"], ["250", "--bike-weight", "-1"]]:
            with self.subTest(invalid=invalid):
                with self.assertRaises(SystemExit):
                    parse_args(invalid)

    def test_cli_execution(self) -> None:
        sample = [
            {"name": "B", "total_distance_km": 30.0, "elevation_m": 200},
            {"name": "A", "total_distance_km": 10.0, "elevation_m": 0},
        ]
        script_path = Path(__file__).resolve().parent / "estimate_route_time.py"

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            input_file = tmp / "routes.json"
            output_file = tmp / "out.json"
            input_file.write_text(json.dumps(sample), encoding="utf-8")

            res = subprocess.run(
                [
                    sys.executable,
                    str(script_path),
                    "250",
                    "--input",
                    str(input_file),
                    "--output",
                    str(output_file),
                    "--sort",
                    "asc",
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertIn("完了:", res.stdout)

            result = json.loads(output_file.read_text(encoding="utf-8"))
            self.assertEqual([r["name"] for r in result], ["A", "B"])
            self.assertRegex(result[0]["estimated_time"], r"^\d{2,}:\d{2}:\d{2}$")


if __name__ == "__main__":
    unittest.main()
