import csv
import json
import os
import re
import requests
from bs4 import BeautifulSoup

OUTPUT_JSON = "master_routes.json"

GITHUB_DATA_URLS = [
    # "https://raw.githubusercontent.com/jeroni7100/zwift-data/master/routes.json",
    # "https://raw.githubusercontent.com/zoffline/zwift-offline/master/data/routes.json",
]

ZWIFT_INSIDER_URL = "https://zwiftinsider.com/routes/"


def parse_number(val, as_int: bool = False):
    """'17.3 km' や '1,045 m' などの文字列から数値を安全に抽出する"""
    if val is None:
        return 0 if as_int else 0.0
    if isinstance(val, (int, float)):
        return int(val) if as_int else float(val)

    cleaned = re.sub(r"[^\d\.]", "", re.sub(r"\(.+", "", str(val)))
    if not cleaned:
        return 0 if as_int else 0.0
    num = float(cleaned)
    return int(round(num)) if as_int else round(num, 2)


def normalize_distance_to_km(raw_val, is_meters_key: bool = False) -> float:
    """メートル表記または500超の数値（メートル単位とみなす）をkmに変換"""
    val = parse_number(raw_val, as_int=False)
    if is_meters_key or val > 500:
        return round(val / 1000.0, 2)
    return round(val, 2)


def normalize_record(raw: dict) -> dict | None:
    """JSON/CSVの各レコードからリードイン距離と合計距離を含む統一フォーマットへ変換"""
    name = raw.get("name") or raw.get("route") or raw.get("title")
    if not name:
        return None

    world = raw.get("world") or raw.get("map") or "Unknown"

    # 1. ルート本体距離 (distance_km)
    dist_raw = (
        raw.get("distance_km")
        if "distance_km" in raw
        else raw.get("distanceInMeters")
        if "distanceInMeters" in raw
        else raw.get("distance") or raw.get("length") or 0
    )
    is_dist_meters = "distanceInMeters" in raw
    dist_km = normalize_distance_to_km(dist_raw, is_dist_meters)

    # 2. リードイン距離 (lead_in_km) のキー揺れ吸収
    lead_raw = None
    is_lead_meters = False
    for key in ["lead_in_km", "leadInDistanceInMeters", "lead_in", "leadin", "leadIn", "leadInDistance"]:
        if key in raw and raw[key] is not None:
            lead_raw = raw[key]
            is_lead_meters = "Meters" in key
            break
    lead_in_km = normalize_distance_to_km(lead_raw, is_lead_meters) if lead_raw is not None else 0.0

    # 3. 実質合計距離 (total_distance_km)
    total_km = round(dist_km + lead_in_km, 2)

    # 4. 獲得標高 (m) ※リードイン標高が別キーである場合は加算
    elev = (
        raw.get("elevation_m")
        or raw.get("ascentInMeters")
        or raw.get("elevation")
        or raw.get("ascent")
        or 0
    )
    elev_val = parse_number(elev, as_int=True)

    lead_elev = raw.get("leadInAscentInMeters") or raw.get("lead_in_elevation") or 0
    elev_val += parse_number(lead_elev, as_int=True)

    # 5. バッジXP
    # xp = raw.get("xp") or raw.get("experience") or raw.get("badge_xp") or 0
    # xp_val = parse_number(xp, as_int=True)

    return {
        "name": str(name).strip(),
        "world": str(world).strip(),
        "distance_km": dist_km,
        "lead_in_km": lead_in_km,
        "total_distance_km": total_km,
        "elevation_m": elev_val,
        # "xp": xp_val,
    }


def fetch_from_github() -> list[dict]:
    """GitHub上のオープンデータからJSONを取得・変換"""
    headers = {"User-Agent": "Mozilla/5.0"}
    for url in GITHUB_DATA_URLS:
        try:
            print(f"GitHubデータ取得試行: {url}")
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code != 200:
                continue

            data = resp.json()
            raw_list = data if isinstance(data, list) else list(data.values())
            results = []
            for item in raw_list:
                if isinstance(item, dict):
                    rec = normalize_record(item)
                    if rec:
                        results.append(rec)

            if len(results) > 50:
                print(f"成功: GitHubから {len(results)} 件のルートを取得しました。")
                return results
        except Exception as e:
            print(f"  スキップ ({e})")

    return []


def extract_km_from_cell(cell_text: str) -> float:
    """'17.3 km (10.7 mi)' や '0.4 km (0.2 mi)' などのセル文字列からkm数値を抽出"""
    if not cell_text or cell_text.strip() in {"-", "—", "N/A", ""}:
        return 0.0
    m = re.search(r"([\d\.]+)\s*km", cell_text, re.IGNORECASE)
    if m:
        return round(float(m.group(1)), 2)
    return parse_number(cell_text, as_int=False)


def fetch_from_html_table(url_or_path: str) -> list[dict]:
    """HTMLテーブルからリードイン列を含めてルート表を解析"""
    print(f"HTMLテーブル解析を試行: {url_or_path}")
    if os.path.exists(url_or_path):
        with open(url_or_path, "r", encoding="utf-8") as f:
            html = f.read()
    else:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        resp = requests.get(url_or_path, headers=headers, timeout=20)
        resp.raise_for_status()
        html = resp.text

    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if not table:
        return []

    headers_text = [th.get_text(strip=True).lower() for th in table.find_all("th")]
    col_idx = {
        "name": 0,
        "world": 1,
        "distance": 2,
        "elevation": 3,
        "lead_in": 4,
        # "xp": 4,
        "restriction": 5,
    }

    for i, h in enumerate(headers_text):
        if "route" in h or "name" in h:
            col_idx["name"] = i
        elif "world" in h:
            col_idx["world"] = i
        elif "lead" in h:
            col_idx["lead_in"] = i
        elif "distance" in h or "length" in h or "km" in h:
            col_idx["distance"] = i
        elif "elevation" in h or "ascent" in h:
            col_idx["elevation"] = i
        # elif "xp" in h:
        #    col_idx["xp"] = i
        elif "restriction" in h:
            col_idx["restriction"] = i

    results = []
    required_max_idx = max(v for v in col_idx.values() if v is not None)

    for tr in table.find_all("tr")[1:]:
        cells = [td.get_text(" ", strip=True) for td in tr.find_all(["td", "th"])]
        if len(cells) <= required_max_idx:
            continue

        name = cells[col_idx["name"]]
        if not name:
            continue

        dist_km = extract_km_from_cell(cells[col_idx["distance"]])
        lead_in_km = (
            extract_km_from_cell(cells[col_idx["lead_in"]])
            if col_idx["lead_in"] is not None
            else 0.0
        )
        total_km = round(dist_km + lead_in_km, 2)

        elev_match = re.search(r"([\d,]+)\s*m\b", cells[col_idx["elevation"]], re.IGNORECASE)
        elev_m = (
            parse_number(elev_match.group(1), as_int=True)
            if elev_match
            else parse_number(cells[col_idx["elevation"]], as_int=True)
        )

        # xp_val = parse_number(cells[col_idx["xp"]], as_int=True)

        restriction = cells[col_idx["restriction"]]
        if "Event Only" in restriction:
            continue

        results.append({
            "name": name,
            "world": cells[col_idx["world"]],
            "distance_km": dist_km,
            "lead_in_km": lead_in_km,
            "total_distance_km": total_km,
            "elevation_m": elev_m,
            # "xp": xp_val,
        })

    return results


def convert_local_csv_to_json(csv_path: str) -> list[dict]:
    """ローカルCSVからの変換ヘルパー"""
    results = []
    with open(csv_path, mode="r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            lower_row = {k.lower().strip(): v for k, v in row.items() if k}
            rec = normalize_record(lower_row)
            if rec:
                results.append(rec)
    return results


def main():
    routes = []

    if os.path.exists("routes_source.csv"):
        print("ローカルの routes_source.csv から変換します...")
        routes = convert_local_csv_to_json("routes_source.csv")
    elif os.path.exists("routes_source.html"):
        print("ローカルの routes_source.html から変換します...")
        routes = fetch_from_html_table("routes_source.html")

    if not routes:
        routes = fetch_from_github()

    if not routes:
        try:
            routes = fetch_from_html_table(ZWIFT_INSIDER_URL)
        except Exception as e:
            print(f"HTML取得エラー: {e}")

    if not routes:
        print("エラー: ルートデータを取得できませんでした。'routes_source.html' を保存して再実行してください。")
        return

    unique_routes = {}
    for r in routes:
        key = (r["world"].lower(), r["name"].lower())
        unique_routes[key] = r

    sorted_routes = sorted(unique_routes.values(), key=lambda x: (x["world"], x["name"]))

    with open(OUTPUT_JSON, mode="w", encoding="utf-8") as f:
        json.dump(sorted_routes, f, ensure_ascii=False, indent=2)

    # リードインデータが取得できた件数をサマリー表示
    with_lead_in = sum(1 for r in sorted_routes if r["lead_in_km"] > 0)
    print(f"\n完了: {len(sorted_routes)} 件のルートマスタを {OUTPUT_JSON} に保存しました（うちリードインあり: {with_lead_in} 件）。")


if __name__ == "__main__":
    main()
