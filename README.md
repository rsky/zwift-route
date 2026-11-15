# zwift-route

Zwift のルートデータを収集し、スクリーンショットから抽出した未踏ルート（グレーの星印）に対して、FTP・体重・走行強度に基づく推定完走時間の算出および目標時間ごとのグループ分けを行う Python ツール群です。

## セットアップ

Python 3.10 以上が必要です。未踏ルート抽出スクリプト（`extract_unridden_routes.py`）は macOS の Vision フレームワーク（`ocrmac`）を利用するため、macOS 環境で実行してください。

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
```

依存パッケージは [pyproject.toml](pyproject.toml) に定義されています（`requests`, `bs4`, `ocrmac`, `pillow`）。

______________________________________________________________________

## 1. マスターデータの作成 (`build_master_routes.py`)

`build_master_routes.py` を実行すると、各ルートの距離・リードイン距離・合計距離・獲得標高を含む `master_routes.json` を生成します。

```bash
.venv/bin/python build_master_routes.py
```

### データ取得の優先順位

1. カレントディレクトリの `routes_source.csv`
2. カレントディレクトリの `routes_source.html`（[Zwift Insider Routes](https://zwiftinsider.com/routes/) の HTML を保存したもの）
3. `https://zwiftinsider.com/routes/` からの直接取得

※ `Event Only` のルートは自動的に除外されます。

______________________________________________________________________

## 2. 未踏ルートを抽出して指定パワー・時間でグループ分けする流れ

スクリーンショットから未踏ルートを抽出し、指定した FTP・強度・目標時間で走破できるグループにまとめる一連の手順です。

### Step 1: スクリーンショットから未踏ルート名を抽出 (`extract_unridden_routes.py`)

ワークアウト指定後のルート選択画面のスクリーンショット（複数指定可）から、グレーの星印が付いた未踏ルートの名前を OCR で抽出します。重複は自動的に排除されます。

```bash
.venv/bin/python extract_unridden_routes.py screenshot_1.png screenshot_2.png -o unridden_names.json
```

- 出力先を省略すると標準出力へ 1 行 1 ルート名で出力します（`--format json` で JSON 出力も可）。

### Step 2: マスターデータと突き合わせて未踏ルート JSON を生成 (`filter_unridden_routes.py`)

抽出したルート名リストと `master_routes.json` を突き合わせ、未踏ルートだけの JSON ファイルを出力します。OCR の軽微な読み誤りは近似マッチ（`--cutoff` デフォルト `0.85`）で吸収します。

```bash
.venv/bin/python filter_unridden_routes.py unridden_names.json --master master_routes.json -o unridden_routes.json
```

> Step 1 と Step 2 をパイプで直接つなぐこともできます：
>
> ```bash
> .venv/bin/python extract_unridden_routes.py screenshot_*.png | .venv/bin/python filter_unridden_routes.py - -o unridden_routes.json
> ```

### Step 3: FTP・強度を指定して推定完走時間を付与 (`estimate_route_time.py`)

未踏ルート JSON に対し、FTP 値（必須）、体重（`--weight`）、FTP に対する走行強度（`--intensity`）などから推定完走時間（`hh:mm:ss` 形式の `estimated_time`）を追加します。

```bash
# 例: FTP 250W、体重 68kg、強度 75% (187.5W) で推定時間を計算し、昇順に並べる
.venv/bin/python estimate_route_time.py 250 --weight 68 --intensity 75 --sort asc --input unridden_routes.json --output unridden_with_time.json
```

| 主なオプション  | デフォルト           | 説明                               |
| --------------- | -------------------- | ---------------------------------- |
| `ftp`           | (必須)               | FTP 値 (W)                         |
| `--weight`      | `70.0`               | ライダーの体重 (kg)                |
| `--intensity`   | `75.0`               | FTP に対する走行強度の割合 (%)     |
| `--bike-weight` | `8.0`                | バイク等の重量 (kg)                |
| `--input`       | `master_routes.json` | 入力 JSON ファイルパス             |
| `--output`      | 入力ファイルを上書き | 出力 JSON ファイルパス             |
| `--sort`        | ソートしない         | `asc`（昇順）または `desc`（降順） |

### Step 4: 目標走行時間のグループにまとめる (`group_routes.py`)

推定完走時間が付いた JSON を読み込み、総走行時間が指定範囲（デフォルト `50分〜70分`）に収まるようルートをグループ化します。上限を超えるルートは単独グループになります。

```bash
# 例: 50分〜1時間10分のグループにまとめて JSON 出力
.venv/bin/python group_routes.py --input unridden_with_time.json --min-minutes 50 --max-minutes 70 --output route_groups.json
```

- `--output` を省略すると、標準出力にグループごとの合計時間とルート一覧を表示します。

### （参考）`jq` を使った結果の確認例

```bash
# 複数ルートが組み合わさったグループ（route_count >= 2）だけ抽出
jq '[.[] | select(.route_count >= 2)]' route_groups.json

# グループID・合計時間・ルート名一覧を見やすく表示
jq '.[] | select(.route_count >= 2) | {group_id, total_estimated_time, route_count, routes: [.routes[].name]}' route_groups.json
```

______________________________________________________________________

## テストの実行

```bash
.venv/bin/python -m unittest -v
```
