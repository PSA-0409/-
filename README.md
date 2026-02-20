# Micro-Float Screener

Fully automated micro-float stock screening + risk management with Alpha Vantage, OpenAI Chat Completions, and Discord notifications.

## Features
- Alpha Vantage data collection with retry/backoff and intraday fallbacks.
- Core metrics: Float Rotation, RVOL, VWAP, VDU ratio, and RangeRatio.
- Japanese structured prompt for Compression→Ignition→Expansion detection and Distribution→Collapse exclusion.
- Discord webhook notifications with message chunking.
- CLI execution and scheduling guidance.

## Setup
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create `.env` from the example and set keys:
```bash
cp .env.example .env
```
Do not commit your `.env` file. Keep API keys in environment variables only.

Environment variables:
- `OPENAI_API_KEY` (required)
- `OPENAI_MODEL` (optional, default `gpt-4o-mini`)
- `DISCORD_WEBHOOK_URL` (required for Discord notifications)
- `ALPHAVANTAGE_API_KEY` (required for market data)

## Usage
### CLI
```bash
python -m screener --tickers TICK1,TICK2 --notify discord --interval 1m --top 5
```

You can also provide tickers via `tickers.txt` (one per line). If `--tickers` is omitted, the file is used.

## Scheduling (cron example)
```bash
# Run every weekday at 9:45 AM ET (server time must be aligned)
45 9 * * 1-5 cd /path/to/project && /path/to/.venv/bin/python -m screener --notify discord
```

## Outputs
- LLM response: `outputs/YYYYMMDD_HHMM_analysis.md`
- JSON payload sent to LLM: `outputs/YYYYMMDD_HHMM_payload.json`
- Logs: `logs/YYYYMMDD_HHMMSS.log`

---

## PR通知Bot

SEC EDGAR に提出された 8-K ファイリング（プレスリリース）を監視し、新着を日本語に翻訳して Discord へ通知します。

### 機能
| 機能 | 説明 |
|------|------|
| 新着PR監視 | SEC EDGAR Atom フィードを定期ポーリング |
| 優先度ハイライト | 大型契約・政府契約・M&A・FDA承認 → 🔴赤Embed / 注目案件 → 🟠橙 / 通常 → 🔵青 |
| 浮動株・時価総額 | Alpha Vantage OVERVIEW から取得して Embed フィールドに表示 |
| 英→日翻訳 | OpenAI (gpt-4o-mini) でタイトル・概要を日本語化 |

### 使い方

```bash
# 指定ティッカーを1回だけポーリング
python -m screener.pr_main --tickers AAPL,TSLA --once

# 5分ごとに継続監視（tickers.txt を参照）
python -m screener.pr_main --interval 300

# 翻訳スキップ（英語のまま通知）
python -m screener.pr_main --tickers AAPL --no-translate
```

### cron 例

```bash
# 平日 9:30〜16:00 に5分ごと実行
*/5 9-16 * * 1-5 cd /path/to/project && /path/to/.venv/bin/python -m screener.pr_main --once
```

### 優先度の判定ロジック

キーワードマッチング（`pr_analyzer.py`）と LLM 分類を組み合わせています。

| 優先度 | 判定条件例 |
|--------|-----------|
| 🔴 critical | `$XB` (十億ドル規模) / merger / acquisition / DOD / FDA approval / patent grant |
| 🟠 high | `$XM` (百万ドル規模) / contract award / government contract / MOU / LOI / licensing |
| 🔵 normal | 上記以外 |

### 出力ファイル
- `outputs/pr_seen.json` — 通知済みエントリのIDリスト（重複送信防止）

---

## Troubleshooting
- **Alpha Vantage missing fields**: floatShares/bid-ask are not provided. The screener estimates float from SharesOutstanding and marks missing data as `推定` in the LLM prompt.
- **Alpha Vantage rate limits**: free tier is limited. The screener retries with backoff, and you should schedule accordingly.
- **Discord length limit**: messages are chunked by paragraph to stay below 2000 characters.
- **Markets closed**: intraday bars may be unavailable. The screener will fall back to recent daily data and label metrics as estimated.
