"""group_routes.py のユニットテスト。"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from group_routes import group_routes, parse_hhmmss


class TestGroupRoutes(unittest.TestCase):
    def test_parse_hhmmss(self) -> None:
        self.assertEqual(parse_hhmmss("00:50:00"), 3000)
        self.assertEqual(parse_hhmmss("01:10:00"), 4200)
        self.assertEqual(parse_hhmmss("02:05:09"), 7509)

        for bad in ["50:00", "00:60:00", "00:00:60", "-01:00:00", "aa:bb:cc"]:
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    parse_hhmmss(bad)

    def test_group_routes_packing_and_solo(self) -> None:
        routes = [
            {"name": "Long", "estimated_time": "01:30:00"},
            {"name": "MediumA", "estimated_time": "00:40:00"},
            {"name": "MediumB", "estimated_time": "00:35:00"},
            {"name": "ShortA", "estimated_time": "00:25:00"},
            {"name": "ShortB", "estimated_time": "00:20:00"},
        ]

        groups = group_routes(routes)
        # 40+25=65分, 35+20=55分, 90分は単独
        self.assertEqual(len(groups), 3)

        packed = [g for g in groups if g["total_estimated_time"] != "01:30:00"]
        solo = [g for g in groups if g["total_estimated_time"] == "01:30:00"]
        self.assertEqual(len(solo), 1)
        self.assertEqual(solo[0]["route_count"], 1)
        self.assertEqual(solo[0]["routes"][0]["name"], "Long")

        for g in packed:
            sec = parse_hhmmss(g["total_estimated_time"])
            self.assertGreaterEqual(sec, 50 * 60)
            self.assertLessEqual(sec, 70 * 60)

    def test_rebalance_underfilled_bin(self) -> None:
        # 45+20=65, 40 だけだと 40<50 になるケースでも、再配分や優先充填で救済可能なら 50〜70分に収まる
        routes = [
            {"name": "R1", "estimated_time": "00:45:00"},
            {"name": "R2", "estimated_time": "00:30:00"},
            {"name": "R3", "estimated_time": "00:20:00"},
            {"name": "R4", "estimated_time": "00:20:00"},
        ]
        groups = group_routes(routes)
        for g in groups:
            sec = parse_hhmmss(g["total_estimated_time"])
            self.assertGreaterEqual(sec, 50 * 60)
            self.assertLessEqual(sec, 70 * 60)

    def test_cli_output_json(self) -> None:
        sample = [
            {"name": "R1", "estimated_time": "00:30:00"},
            {"name": "R2", "estimated_time": "00:30:00"},
            {"name": "R3", "estimated_time": "01:20:00"},
        ]
        script_path = Path(__file__).resolve().parent / "group_routes.py"

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            input_file = tmp / "in.json"
            output_file = tmp / "groups.json"
            input_file.write_text(json.dumps(sample), encoding="utf-8")

            res = subprocess.run(
                [
                    sys.executable,
                    str(script_path),
                    "--input",
                    str(input_file),
                    "--output",
                    str(output_file),
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertIn("完了:", res.stdout)

            data = json.loads(output_file.read_text(encoding="utf-8"))
            self.assertEqual(len(data), 2)
            self.assertEqual(data[0]["total_estimated_time"], "01:00:00")
            self.assertEqual(data[0]["route_count"], 2)
            self.assertEqual(data[1]["total_estimated_time"], "01:20:00")
            self.assertEqual(data[1]["route_count"], 1)


if __name__ == "__main__":
    unittest.main()
