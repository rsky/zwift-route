"""estimate_route_time.py の出力JSONを読み取り、総走行時間が指定範囲 (デフォルト50〜70分) になるようルートをグループ化するスクリプト。"""

import argparse
import json
from dataclasses import dataclass, field as dataclass_field
from pathlib import Path

from estimate_route_time import format_hhmmss


@dataclass
class _RouteBin:
    """グルーピング途中のビン（ルートと秒数のペア、および合計秒数）を保持する。"""

    items: list[tuple[dict, int]] = dataclass_field(default_factory=list)
    total_seconds: int = 0

    def add(self, route: dict, seconds: int) -> None:
        self.items.append((route, seconds))
        self.total_seconds += seconds


def parse_hhmmss(time_str: str) -> int:
    """hh:mm:ss 形式の文字列を秒数 (int) に変換する。"""
    parts = time_str.strip().split(":")
    if len(parts) != 3:
        raise ValueError(f"hh:mm:ss 形式ではありません: {time_str}")
    hours, minutes, seconds = (int(p) for p in parts)
    if hours < 0 or not (0 <= minutes < 60) or not (0 <= seconds < 60):
        raise ValueError(f"時刻の値が不正です: {time_str}")
    return hours * 3600 + minutes * 60 + seconds


def _find_target_bin(
    bins: list[_RouteBin],
    seconds: int,
    min_seconds: int,
    max_seconds: int,
) -> _RouteBin | None:
    """追加可能な最初のビンを返す。min_seconds 未満のビンを優先する。"""
    for b in bins:
        if b.total_seconds < min_seconds and b.total_seconds + seconds <= max_seconds:
            return b
    for b in bins:
        if b.total_seconds + seconds <= max_seconds:
            return b
    return None


def _try_fill_bin(
    target: _RouteBin,
    bins: list[_RouteBin],
    min_seconds: int,
    max_seconds: int,
) -> None:
    """他の複数ルートビンから1ルートずつ移動し、target を min_seconds 以上に引き上げる。"""
    for donor in bins:
        if donor is target or len(donor.items) <= 1:
            continue
        for idx, (route, sec) in enumerate(donor.items):
            if donor.total_seconds - sec >= min_seconds and target.total_seconds + sec <= max_seconds:
                donor.items.pop(idx)
                donor.total_seconds -= sec
                target.add(route, sec)
                if target.total_seconds >= min_seconds:
                    return


def _rebalance_underfilled_bins(
    bins: list[_RouteBin],
    min_seconds: int,
    max_seconds: int,
) -> None:
    """min_seconds 未満のビンがある場合、他の複数ルートビンからの移動で解消を試みる。"""
    for target in bins:
        if target.total_seconds < min_seconds:
            _try_fill_bin(target, bins, min_seconds, max_seconds)


def group_routes(
    routes: list[dict],
    min_seconds: int = 50 * 60,
    max_seconds: int = 70 * 60,
    field: str = "estimated_time",
) -> list[dict]:
    """ルート一覧を指定の総走行時間範囲のグループにまとめる。

    max_seconds を超えるルートは単独グループとする。
    """
    if min_seconds < 0 or max_seconds < min_seconds:
        raise ValueError("min_seconds <= max_seconds かつ 0 以上を指定してください。")

    solo_bins: list[_RouteBin] = []
    packable: list[tuple[dict, int]] = []

    for record in routes:
        if not isinstance(record, dict) or field not in record:
            raise ValueError(f"レコードに '{field}' フィールドがありません: {record}")
        sec = parse_hhmmss(str(record[field]))
        if sec > max_seconds:
            solo_bins.append(_RouteBin(items=[(record, sec)], total_seconds=sec))
        else:
            packable.append((record, sec))

    # 降順 (First-Fit Decreasing) で詰める
    packable.sort(key=lambda item: item[1], reverse=True)
    packed_bins: list[_RouteBin] = []

    for record, sec in packable:
        target = _find_target_bin(packed_bins, sec, min_seconds, max_seconds)
        if target is None:
            packed_bins.append(_RouteBin(items=[(record, sec)], total_seconds=sec))
        else:
            target.add(record, sec)

    _rebalance_underfilled_bins(packed_bins, min_seconds, max_seconds)

    return [
        {
            "group_id": idx,
            "total_estimated_time": format_hhmmss(b.total_seconds),
            "route_count": len(b.items),
            "routes": [route for route, _ in b.items],
        }
        for idx, b in enumerate(packed_bins + solo_bins, start=1)
    ]


def non_negative_int(value: str) -> int:
    """argparse用の0以上の整数バリデータ。"""
    try:
        num = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"整数を指定してください: {value}") from exc
    if num < 0:
        raise argparse.ArgumentTypeError(f"0以上の整数を指定してください: {value}")
    return num


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="推定完走時間をもとにルートを50分〜1時間10分のグループにまとめます。"
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
        help="出力JSONファイルパス (省略時は標準出力にサマリーを表示)",
    )
    parser.add_argument(
        "--field",
        default="estimated_time",
        help="推定時間のフィールド名 [デフォルト: estimated_time]",
    )
    parser.add_argument(
        "--min-minutes",
        type=non_negative_int,
        default=50,
        help="グループの目標最小時間 (分) [デフォルト: 50]",
    )
    parser.add_argument(
        "--max-minutes",
        type=non_negative_int,
        default=70,
        help="グループの最大時間 (分)。これを超えるルートは単独 [デフォルト: 70]",
    )
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()
    if args.min_minutes > args.max_minutes:
        raise SystemExit("エラー: --min-minutes は --max-minutes 以下にしてください。")
    if not args.input.exists():
        raise SystemExit(f"エラー: 入力ファイルが見つかりません: {args.input}")

    with args.input.open("r", encoding="utf-8") as f:
        routes = json.load(f)

    if not isinstance(routes, list):
        raise SystemExit("エラー: JSONのルート要素は配列である必要があります。")

    groups = group_routes(
        routes=routes,
        min_seconds=args.min_minutes * 60,
        max_seconds=args.max_minutes * 60,
        field=args.field,
    )

    if args.output is not None:
        with args.output.open("w", encoding="utf-8") as f:
            json.dump(groups, f, ensure_ascii=False, indent=2)
        print(f"完了: {len(routes)} 件のルートを {len(groups)} グループにまとめ、{args.output} に保存しました。")
        return

    for g in groups:
        names = ", ".join(f"{r.get('name', 'Unknown')} ({r[args.field]})" for r in g["routes"])
        print(f"[{g['group_id']:03d}] 合計 {g['total_estimated_time']} ({g['route_count']}件): {names}")


if __name__ == "__main__":
    main()
