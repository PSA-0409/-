# Morning Scanner — Claude Code コンテキスト

## プロジェクト概要

米国株スクリーナー。毎朝マーケットクローズ後に実行し、3カテゴリの銘柄リストを生成・通知する。

-----

## スクリプトの仕様

### ◆ Gainers（Chg >= 30%）Top 15

- 終値ベースで前日比 +30% 以上の銘柄
- 上位15銘柄を変動率の降順で出力
- 表示項目: Ticker / 終値 / 前日比(%) / 出来高 / 時価総額

### ◆ Day1 Target

抽出条件（すべてAND）:

- 前日比: +50% 〜 +500%
- 回転率（Volume / Float）: >= 200%
- 陽線（終値 > 始値）

タグ付け条件（合致する場合に各タグを付与）:

- `$2-8`: 終値が $2.00 〜 $8.00
- `SmallFloat`: Float <= 10M株
- `RVOL5+`: RVOL（当日出来高 / 平均出来高20日）>= 5
- `NearHigh`: 終値 >= 高値の 70% 以上（高値から30%以内）

出力項目: Ticker / 終値 / 前日比(%) / Float / RVOL / 回転率 / 高値比(%) / タグ

### ◆ Day2 Target

前回実行時に保存した Day1 Target リストを参照して抽出。

抽出条件（すべてAND）:

- 前日比: -30% 〜 0%（マイナス圏）
- Day2高値 <= Day1高値
- Day2出来高 < Day1出来高（出来高縮小）
- Day2出来高 / Day1出来高: >= 4%（最低限の流動性）

タグ付け条件:

- `D2/D1_Low`: Day2/Day1出来高比 0.04 〜 0.10（出来高が大幅に縮小）
- `Green`: Day2終値 > Day2始値（陽線）

出力項目: Ticker / Day2終値 / Day2前日比(%) / D2/D1出来高比 / Day2高値 vs Day1高値 / タグ

-----

## データソース

### 優先順位

1. **FMP API**（Financial Modeling Prep） — 財務データ・株価・Float
1. **Polygon.io API** — 分足・出来高データ（FMPで取れない場合）
1. **Yahoo Finance (yfinance)** — フォールバック用（Float情報が不安定なため補助的に使用）

### 必須データ項目

|項目         |ソース|エンドポイント例                        |
|-----------|---|--------------------------------|
|終値・始値・高値・安値|FMP|`/historical-price-eod/full`    |
|出来高        |FMP|`/historical-price-eod/full`    |
|Float株数    |FMP|`/shares-float`                 |
|平均出来高（20日） |FMP|`/historical-price-eod/full` で計算|
|スクリーナー対象銘柄 |FMP|`/stock-screener` または `/gainers`|

-----

## ディレクトリ構成

```
project/
├── CLAUDE.md                        # 本ファイル
├── .env                             # APIキー（git管理外）
├── scanner.py                       # メインスクリプト
├── notifier.py                      # 通知モジュール
├── data/
│   └── day1_targets_YYYYMMDD.json   # Day1結果の永続化（Day2判定に使用）
├── output/
│   └── YYYYMMDD_morning_scan.md     # 日次レポート
├── logs/
│   └── YYYYMMDD_scanner.log         # 実行ログ
└── docs/
    └── knowledges/                  # 蓄積知識
```

-----

## ファイル命名規則

- **必須**: `YYYYMMDD_` プレフィックスを日次ファイルに付与
- 例: `20260221_morning_scan.md`、`day1_targets_20260221.json`
- ログは `logs/YYYYMMDD_scanner.log` に追記

-----

## コーディング規約

### 言語・ライブラリ

- Python 3.10+
- `requests` — API通信
- `pandas` — データ処理
- `python-dotenv` — 環境変数管理
- `schedule` または `cron` — 定期実行

### スタイル

- ES modules ではなく Python の慣習に従う
- 型ヒント（Type Hints）を必ず付与
- `print()` を本番コードに残さない（`logging` モジュールを使用）
- モック・ダミーデータは使用禁止（テスト時は明示的にフラグで切り替え）

### エラーハンドリング

- API エラー（429 / 503）はエクスポネンシャルバックオフでリトライ（最大3回）
- データ取得失敗時はその銘柄をスキップし、ログに記録してスクリプトは継続
- 致命的エラーのみ全体を停止し、通知に `[ERROR]` を付けて送信

-----

## 通知仕様

### 通知タイミング

- 毎朝 **07:00 ET**（米国東部時間）に自動実行
- 手動実行: `python scanner.py --date YYYYMMDD`

### 通知先（優先順位で設定）

- **Discord Webhook**（推奨）: `DISCORD_WEBHOOK_URL` 環境変数
- **メール**（代替）: `SMTP_*` 環境変数
- **ローカルファイル**: 常に `output/` に保存（通知の成否に関わらず）

### 通知フォーマット

```
📊 Morning Scan — 2026/02/21

━━━━━━━━━━━━━━━━━━━━━━
◆ Gainers Top 15（+30%以上）
━━━━━━━━━━━━━━━━━━━━━━
1. TICKER  $X.XX  +XX.X%  Vol:XXXk
...（15銘柄）

━━━━━━━━━━━━━━━━━━━━━━
◆ Day1 Target（X銘柄）
━━━━━━━━━━━━━━━━━━━━━━
TICKER  $X.XX  +XXX%  Float:XM  RVOL:X.X  [タグ1][タグ2]
...

━━━━━━━━━━━━━━━━━━━━━━
◆ Day2 Target（X銘柄）
━━━━━━━━━━━━━━━━━━━━━━
TICKER  $X.XX  -XX%  D2/D1:0.XX  [タグ1][タグ2]
...

実行時刻: 07:02 ET | データ取得: FMP API
```

-----

## 環境変数（.env）

```env
FMP_API_KEY=your_key_here
POLYGON_API_KEY=your_key_here        # オプション
DISCORD_WEBHOOK_URL=your_webhook_here  # 通知先
SMTP_HOST=smtp.gmail.com             # メール通知の場合
SMTP_PORT=587
SMTP_USER=your_email
SMTP_PASS=your_password
NOTIFY_EMAIL=recipient@example.com
```

-----

## Day1データの永続化ルール

- Day1 Target の結果は `data/day1_targets_YYYYMMDD.json` に保存する
- Day2判定時は「前営業日」の Day1 ファイルを自動検索する
- ファイルが存在しない場合は Day2 セクションをスキップし、ログに記録する
- 保存するフィールド: `ticker`, `date`, `close`, `high`, `volume`, `float`, `tags`

-----

## 計算定義（明確化）

|指標       |計算式                       |
|---------|--------------------------|
|前日比(%)   |`(終値 - 前日終値) / 前日終値 * 100`|
|回転率(%)   |`当日出来高 / Float株数 * 100`   |
|RVOL     |`当日出来高 / 過去20営業日平均出来高`    |
|高値比(%)   |`終値 / 当日高値 * 100`         |
|D2/D1出来高比|`Day2出来高 / Day1出来高`       |

-----

## 禁止事項

- 未検証の数値を事実として通知に含める
- モック・ダミーデータを実際のデータとして使用する
- `print()` を本番コードに残す（`logging` を使用）
- APIキーをコードに直書きする
- 「買いです」などの売買推奨表現を通知に含める
- エラー発生時にサイレントで処理を継続する（必ずログ記録）

-----

## 開発・テスト方針

- バックテスト用に `--date` オプションで過去日付を指定して実行可能にする
- テストモード（`--dry-run`）では通知を送らずコンソール出力のみ
- Float データの欠損は `【要確認】` フラグを立てて出力に含める（スキップしない）
- スクリーナー対象は米国市場（NYSE / NASDAQ / AMEX）のみ。OTCは除外する

-----

## 優先スキャン対象（新セッション開始時）

1. `data/day1_targets_*.json` — 最新の Day1 保存ファイル
1. `logs/` — 直近の実行ログ（エラー確認）
1. `docs/knowledges/` — 蓄積された計算ロジック・API仕様メモ
