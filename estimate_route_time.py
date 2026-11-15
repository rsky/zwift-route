"""master_routes.json の各ルートに対して、FTP値から推定完走時間を算出し hh:mm:ss 形式で追加するスクリプト。"""

import argparse
import json
import math
from pathlib import Path
from typing import Literal

# 物理定数・Zwift標準バイクのデフォルトパラメータ
GRAVITY = 9.80665  # m/s^2
AIR_DENSITY = 1.225  # kg/m^3
DEFAULT_CDA = 0.32  # m^2 (前面投影面積 × 空気抵抗係数)
DEFAULT_CRR = 0.004  # 転がり抵抗係数
DRIVETRAIN_EFFICIENCY = 0.975  # 駆動伝達効率

SortOrder = Literal["asc", "desc"]


def solve_speed_mps(
    power_watts: float,
    total_mass_kg: float,
    grade: float,
    cda: float = DEFAULT_CDA,
    crr: float = DEFAULT_CRR,
) -> float:
    """指定されたパワー・総重量・勾配における定常速度 (m/s) を二分法で求める。"""
    wheel_power = power_watts * DRIVETRAIN_EFFICIENCY
    theta = math.atan(grade)
    aero_coeff = 0.5 * AIR_DENSITY * cda
    resist_coeff = total_mass_kg * GRAVITY * (crr * math.cos(theta) + math.sin(theta))

    def power_residual(v: float) -> float:
        return (aero_coeff * v * v + resist_coeff) * v - wheel_power

    low = 0.0
    high = 100.0  # 360 km/h (下りでも十分に上界となる速度)
    for _ in range(60):
        mid = 0.5 * (low + high)
        if power_residual(mid) < 0.0:
            low = mid
        else:
            high = mid
    return 0.5 * (low + high)


def estimate_route_seconds(
    distance_km: float,
    elevation_m: float,
    power_watts: float,
    total_mass_kg: float,
) -> float:
    """総距離と獲得標高から推定完走時間 (秒) を算出する。

    Zwiftの周回コースを想定し、距離の前半を平均登坂勾配 (+2*E/D)、
    後半を平均降坂勾配 (-2*E/D) で走行するモデルで近似する。
    """
    if distance_km <= 0:
        return 0.0

    distance_m = distance_km * 1000.0
    if elevation_m <= 0:
        speed = solve_speed_mps(power_watts, total_mass_kg, 0.0)
        return distance_m / speed

    half_distance_m = distance_m * 0.5
    climb_grade = elevation_m / half_distance_m
    up_speed = solve_speed_mps(power_watts, total_mass_kg, climb_grade)
    down_speed = solve_speed_mps(power_watts, total_mass_kg, -climb_grade)
    return (half_distance_m / up_speed) + (half_distance_m / down_speed)


def format_hhmmss(seconds: float) -> str:
    """秒数を hh:mm:ss 形式の文字列に変換する。"""
    total_seconds = max(0, round(seconds))
    hours, rem = divmod(total_seconds, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def extract_distance_km(record: dict) -> float:
    """レコードから総距離 (km) を抽出する。未設定時は distance_km + lead_in_km を用いる。"""
    total = record.get("total_distance_km")
    if total is not None:
        return float(total)
    return float(record.get("distance_km", 0.0)) + float(record.get("lead_in_km", 0.0))


def add_estimated_times(
    routes: list,
    power_watts: float,
    total_mass_kg: float,
    field: str = "estimated_time",
    sort_order: SortOrder | None = None,
) -> list:
    """ルート一覧の各レコードに推定完走時間を追加し、必要に応じてソートした新しいリストを返す。"""
    routes_with_seconds: list[tuple[object, float]] = []
    for record in routes:
        if not isinstance(record, dict):
            routes_with_seconds.append((record, float("inf")))
            continue

        est_seconds = estimate_route_seconds(
            distance_km=extract_distance_km(record),
            elevation_m=float(record.get("elevation_m", 0.0)),
            power_watts=power_watts,
            total_mass_kg=total_mass_kg,
        )
        updated = {**record, field: format_hhmmss(est_seconds)}
        routes_with_seconds.append((updated, est_seconds))

    if sort_order is not None:
        routes_with_seconds.sort(
            key=lambda item: item[1],
            reverse=(sort_order == "desc"),
        )

    return [record for record, _ in routes_with_seconds]


def _parse_bounded_float(value: str, *, allow_zero: bool) -> float:
    """有限な浮動小数点数をパースし、範囲を検証する。"""
    try:
        num = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"数値を指定してください: {value}") from exc

    if not math.isfinite(num):
        raise argparse.ArgumentTypeError(f"有限の数値を指定してください: {value}")
    if allow_zero and num < 0:
        raise argparse.ArgumentTypeError(f"0以上の数を指定してください: {value}")
    if not allow_zero and num <= 0:
        raise argparse.ArgumentTypeError(f"正の数を指定してください: {value}")
    return num


def positive_float(value: str) -> float:
    """argparse用の正の浮動小数点数バリデータ。"""
    return _parse_bounded_float(value, allow_zero=False)


def non_negative_float(value: str) -> float:
    """argparse用の0以上の浮動小数点数バリデータ。"""
    return _parse_bounded_float(value, allow_zero=True)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="master_routes.json にFTP値からの推定完走時間 (hh:mm:ss) を追加します。"
    )
    parser.add_argument(
        "ftp",
        type=positive_float,
        help="FTP値 (W)",
    )
    parser.add_argument(
        "--weight",
        type=positive_float,
        default=70.0,
        help="ライダーの体重 (kg) [デフォルト: 70.0]",
    )
    parser.add_argument(
        "--intensity",
        type=positive_float,
        default=75.0,
        help="FTPに対する走行強度の割合 (%%) [デフォルト: 75.0]",
    )
    parser.add_argument(
        "--bike-weight",
        type=non_negative_float,
        default=8.0,
        help="バイク等の重量 (kg) [デフォルト: 8.0]",
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("master_routes.json"),
        help="入力JSONファイルパス [デフォルト: master_routes.json]",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="出力JSONファイルパス (省略時は入力ファイルを上書き)",
    )
    parser.add_argument(
        "--field",
        default="estimated_time",
        help="追加するフィールド名 [デフォルト: estimated_time]",
    )
    parser.add_argument(
        "--sort",
        choices=["asc", "desc"],
        default=None,
        help="推定完走時間でソートする (asc: 昇順, desc: 降順) [デフォルト: ソートしない]",
    )
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()
    input_path: Path = args.input
    output_path: Path = args.output if args.output is not None else input_path

    if not input_path.exists():
        raise SystemExit(f"エラー: 入力ファイルが見つかりません: {input_path}")

    with input_path.open("r", encoding="utf-8") as f:
        routes = json.load(f)

    if not isinstance(routes, list):
        raise SystemExit("エラー: JSONのルート要素は配列である必要があります。")

    target_power = args.ftp * (args.intensity / 100.0)
    total_mass = args.weight + args.bike_weight

    updated_routes = add_estimated_times(
        routes=routes,
        power_watts=target_power,
        total_mass_kg=total_mass,
        field=args.field,
        sort_order=args.sort,
    )

    with output_path.open("w", encoding="utf-8") as f:
        json.dump(updated_routes, f, ensure_ascii=False, indent=2)

    print(
        f"完了: {len(updated_routes)} 件のルートに '{args.field}' を追加し、{output_path} に保存しました "
        f"(FTP={args.ftp:g}W, 強度={args.intensity:g}% -> {target_power:.1f}W, 体重={args.weight:g}kg)。"
    )


if __name__ == "__main__":
    main()
