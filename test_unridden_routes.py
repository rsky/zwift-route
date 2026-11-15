"""extract_unridden_routes.py と filter_unridden_routes.py のユニットテスト。"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from extract_unridden_routes import detect_gray_star_icons
from filter_unridden_routes import (
    load_extracted_names,
    match_unridden_routes,
    normalize_route_name,
)


class TestUnriddenRoutes(unittest.TestCase):
    def test_detect_gray_star_icons_on_sample(self) -> None:
        sample = Path(__file__).resolve().parent / "screenshot_sample.png"
        if not sample.exists():
            self.skipTest("screenshot_sample.png が存在しません")
        with Image.open(sample) as img:
            icons = detect_gray_star_icons(img)
        self.assertEqual(len(icons), 4)

    def test_normalize_route_name(self) -> None:
        self.assertEqual(normalize_route_name("  Watopia’s   Waistband "), "watopia's waistband")

    def test_match_unridden_routes(self) -> None:
        master = [
            {"name": "Elevation Evaluation", "world": "Watopia", "distance_km": 24.6},
            {"name": "Downtown Titans", "world": "Watopia", "distance_km": 24.6},
            {"name": "Watopia's Waistband", "world": "Watopia", "distance_km": 25.4},
        ]
        extracted = [
            "Elevation Evaluation",
            "Downtown Titan",  # 1文字欠けの近似マッチ
            "Watopia’s Waistband",  # アポストロフィ揺れ
            "Non Existent Route",
        ]
        matched, unmatched = match_unridden_routes(extracted, master)
        self.assertEqual(
            [r["name"] for r in matched],
            ["Elevation Evaluation", "Downtown Titans", "Watopia's Waistband"],
        )
        self.assertEqual(unmatched, ["Non Existent Route"])

    def test_load_extracted_names_text_and_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            txt_file = tmp / "names.txt"
            txt_file.write_text("Route A\n\nRoute B\n", encoding="utf-8")
            self.assertEqual(load_extracted_names(str(txt_file)), ["Route A", "Route B"])

            json_file = tmp / "names.json"
            json_file.write_text(json.dumps(["Route C", "Route D"]), encoding="utf-8")
            self.assertEqual(load_extracted_names(str(json_file)), ["Route C", "Route D"])

    def test_filter_cli(self) -> None:
        script_path = Path(__file__).resolve().parent / "filter_unridden_routes.py"
        master = [
            {"name": "Elevation Evaluation", "world": "Watopia"},
            {"name": "Serpentine 8", "world": "Watopia"},
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            master_file = tmp / "master.json"
            extracted_file = tmp / "extracted.json"
            out_file = tmp / "unridden.json"
            master_file.write_text(json.dumps(master), encoding="utf-8")
            extracted_file.write_text(json.dumps(["Serpentine 8"]), encoding="utf-8")

            subprocess.run(
                [
                    sys.executable,
                    str(script_path),
                    str(extracted_file),
                    "--master",
                    str(master_file),
                    "--output",
                    str(out_file),
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            result = json.loads(out_file.read_text(encoding="utf-8"))
            self.assertEqual(result, [{"name": "Serpentine 8", "world": "Watopia"}])


if __name__ == "__main__":
    unittest.main()
