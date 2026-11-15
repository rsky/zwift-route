"""Zwiftのルート選択画面スクリーンショットから未踏ルート（グレーの星印）の名前をOCRで抽出するスクリプト。"""

import argparse
import json
import sys
from pathlib import Path

from ocrmac import ocrmac
from PIL import Image


def _is_gray_icon_pixel(r: int, g: int, b: int) -> bool:
    """未踏ルートのグレーアイコン背景色かどうかを判定する。"""
    return 175 <= r <= 232 and max(r, g, b) - min(r, g, b) <= 15


def detect_gray_star_icons(img: Image.Image) -> list[tuple[int, int, int]]:
    """画像内からグレーの星アイコン領域を検出し、(y_top, y_bottom, x_right) のリストを返す。"""
    rgb = img.convert("RGB")
    w, h = rgb.size
    pixels = rgb.load()

    x_start = int(w * 0.280)
    x_end = int(w * 0.328)
    y_start = int(h * 0.08)
    y_end = int(h * 0.90)

    min_count = max(4, int(w * 0.010))
    max_count = max(min_count + 1, int(w * 0.035))
    min_height = max(8, int(h * 0.020))

    active_rows: list[tuple[int, int]] = []
    for y in range(y_start, y_end):
        gray_count = 0
        max_gray_x = 0
        for x in range(x_start, x_end):
            r, g, b = pixels[x, y]
            if _is_gray_icon_pixel(r, g, b):
                gray_count += 1
                max_gray_x = x

        if min_count <= gray_count <= max_count:
            active_rows.append((y, max_gray_x))

    # 縦方向に連続する行をグループ化してアイコンの矩形を確定する
    icons: list[tuple[int, int, int]] = []
    if not active_rows:
        return icons

    group_top = active_rows[0][0]
    group_bottom = active_rows[0][0]
    group_x_right = active_rows[0][1]

    for y, x_right in active_rows[1:]:
        if y - group_bottom <= 3:
            group_bottom = y
            group_x_right = max(group_x_right, x_right)
        else:
            if group_bottom - group_top + 1 >= min_height:
                icons.append((group_top, group_bottom, group_x_right))
            group_top = y
            group_bottom = y
            group_x_right = x_right

    if group_bottom - group_top + 1 >= min_height:
        icons.append((group_top, group_bottom, group_x_right))

    return icons


def extract_unridden_routes_from_image(image_path: Path) -> list[str]:
    """1枚のスクリーンショットから未踏ルート名を抽出する。"""
    with Image.open(image_path) as img:
        w, h = img.size
        icons = detect_gray_star_icons(img)
        if not icons:
            return []

        # ルート名・ワールド名が並ぶ列だけを切り出してOCRを実行する
        crop_x0 = max(0, max(x_r for _, _, x_r in icons) + 4)
        crop_x1 = min(w, int(w * 0.575))
        crop_y0 = int(h * 0.08)
        crop_y1 = int(h * 0.90)

        cropped = img.crop((crop_x0, crop_y0, crop_x1, crop_y1))
        ocr_results = ocrmac.OCR(
            cropped,
            recognition_level="accurate",
            language_preference=["en-US"],
        ).recognize(px=True)

    # PILピクセル座標 (x0, y0, x1, y1) を元画像のY中心座標に変換
    text_blocks: list[tuple[float, str]] = []
    for text, _, (_, y0, _, y1) in ocr_results:
        center_y = crop_y0 + 0.5 * (y0 + y1)
        text_blocks.append((center_y, text.strip()))

    # 各グレーアイコンのY範囲に対応する最上段のテキストをルート名として取得
    extracted: list[str] = []
    for y_top, y_bottom, _ in icons:
        margin = max(6.0, (y_bottom - y_top) * 0.25)
        candidates = [
            (cy, txt)
            for cy, txt in text_blocks
            if (y_top - margin) <= cy <= (y_bottom + margin) and txt
        ]
        if candidates:
            candidates.sort(key=lambda c: c[0])
            extracted.append(candidates[0][1])

    return extracted


def extract_unridden_routes(image_paths: list[Path]) -> list[str]:
    """複数のスクリーンショットから未踏ルート名を抽出し、順序を保って重複排除する。"""
    seen: dict[str, None] = {}
    for path in image_paths:
        if not path.exists():
            raise SystemExit(f"エラー: 画像ファイルが見つかりません: {path}")
        for name in extract_unridden_routes_from_image(path):
            seen[name] = None
    return list(seen.keys())


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Zwiftのルート選択スクリーンショットから未踏ルート名をOCRで抽出します。"
    )
    parser.add_argument(
        "images",
        nargs="+",
        type=Path,
        help="スクリーンショット画像ファイルパス (複数指定可)",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="出力ファイルパス (省略時は標準出力)",
    )
    parser.add_argument(
        "--format",
        choices=["text", "json"],
        default=None,
        help="出力形式 (省略時は出力ファイル拡張子が .json なら json、それ以外は text)",
    )
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()
    names = extract_unridden_routes(args.images)

    fmt = args.format
    if fmt is None:
        fmt = "json" if (args.output and args.output.suffix.lower() == ".json") else "text"

    output_text = (
        json.dumps(names, ensure_ascii=False, indent=2)
        if fmt == "json"
        else "\n".join(names)
    )

    if args.output is not None:
        args.output.write_text(output_text + "\n", encoding="utf-8")
        print(f"完了: {len(names)} 件の未踏ルート名を {args.output} に保存しました。", file=sys.stderr)
    else:
        if output_text:
            print(output_text)


if __name__ == "__main__":
    main()
