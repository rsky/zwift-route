"""OCRで抽出した未踏ルート名リストと master_routes.json を突き合わせ、未踏ルートのみのJSONを出力するスクリプト。"""

import argparse
import difflib
import json
import re
import sys
from pathlib import Path


def normalize_route_name(name: str) -> str:
    """比較用にルート名を正規化する（空白・引用符・大小文字の揺れを吸収）。"""
    normalized = name.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    normalized = re.sub(r"\s+", " ", normalized).strip().lower()
    return normalized


def load_extracted_names(source: str) -> list[str]:
    """抽出済みルート名（JSON配列または1行1件のテキスト、'-' で標準入力）を読み込む。"""
    if source == "-":
        raw = sys.stdin.read()
    else:
        path = Path(source)
        if not path.exists():
            raise SystemExit(f"エラー: 抽出ファイルが見つかりません: {path}")
        raw = path.read_text(encoding="utf-8")

    stripped = raw.strip()
    if not stripped:
        return []

    if stripped.startswith("["):
        data = json.loads(stripped)
        if not isinstance(data, list):
            raise SystemExit("エラー: 抽出JSONは配列である必要があります。")
        return [str(item).strip() for item in data if str(item).strip()]

    return [line.strip() for line in stripped.splitlines() if line.strip()]


def match_unridden_routes(
    extracted_names: list[str],
    master_routes: list[dict],
    cutoff: float = 0.85,
) -> tuple[list[dict], list[str]]:
    """抽出されたルート名をマスターデータと突き合わせ、(一致レコードリスト, 未一致リスト) を返す。"""
    master_index: dict[str, list[dict]] = {}
    for record in master_routes:
        if not isinstance(record, dict) or "name" not in record:
            continue
        key = normalize_route_name(str(record["name"]))
        master_index.setdefault(key, []).append(record)

    master_keys = list(master_index.keys())
    matched_records: list[dict] = []
    seen_records: set[tuple[str, str]] = set()
    unmatched: list[str] = []

    for raw_name in extracted_names:
        norm = normalize_route_name(raw_name)
        hits = master_index.get(norm)

        if hits is None:
            close = difflib.get_close_matches(norm, master_keys, n=1, cutoff=cutoff)
            if close:
                hits = master_index[close[0]]
                matched_name = hits[0].get("name", close[0])
                print(
                    f"近似マッチ: '{raw_name}' -> '{matched_name}'",
                    file=sys.stderr,
                )

        if not hits:
            unmatched.append(raw_name)
            continue

        for rec in hits:
            rec_key = (str(rec.get("world", "")), str(rec.get("name", "")))
            if rec_key not in seen_records:
                seen_records.add(rec_key)
                matched_records.append(rec)

    return matched_records, unmatched


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="抽出した未踏ルート名と master_routes.json を突き合わせて未踏ルートのみのJSONを出力します。"
    )
    parser.add_argument(
        "extracted",
        help="extract_unridden_routes.py の出力ファイルパス ('-' で標準入力)",
    )
    parser.add_argument(
        "--master",
        type=Path,
        default=Path("master_routes.json"),
        help="マスターJSONファイルパス [デフォルト: master_routes.json]",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("unridden_routes.json"),
        help="出力JSONファイルパス [デフォルト: unridden_routes.json]",
    )
    parser.add_argument(
        "--cutoff",
        type=float,
        default=0.85,
        help="完全一致しない場合の近似マッチ類似度閾値 (0.0〜1.0) [デフォルト: 0.85]",
    )
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()
    if not args.master.exists():
        raise SystemExit(f"エラー: マスターファイルが見つかりません: {args.master}")

    with args.master.open("r", encoding="utf-8") as f:
        master_routes = json.load(f)
    if not isinstance(master_routes, list):
        raise SystemExit("エラー: マスターJSONのルート要素は配列である必要があります。")

    extracted_names = load_extracted_names(args.extracted)
    matched, unmatched = match_unridden_routes(
        extracted_names=extracted_names,
        master_routes=master_routes,
        cutoff=args.cutoff,
    )

    with args.output.open("w", encoding="utf-8") as f:
        json.dump(matched, f, ensure_ascii=False, indent=2)

    print(
        f"完了: {len(extracted_names)} 件中 {len(matched)} 件の未踏ルートを {args.output} に保存しました。"
    )
    if unmatched:
        print(f"警告: マスターに一致しなかったルート ({len(unmatched)} 件): {unmatched}", file=sys.stderr)


if __name__ == "__main__":
    main()
