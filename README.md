# Micro-Float Screener

Fully automated micro-float stock screening + risk management with Alpha Vantage, OpenAI Chat Completions, and Discord/Notion notifications.

## Features
- Alpha Vantage data collection with retry/backoff and intraday fallbacks.
- Core metrics: Float Rotation, RVOL, VWAP, VDU ratio, and RangeRatio.
- Japanese structured prompt for Compression→Ignition→Expansion detection and Distribution→Collapse exclusion.
- Discord webhook notifications with message chunking.
- Notion database notifications for archived daily reports.
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
- `NOTION_API_KEY` (required for Notion notifications)
- `NOTION_DATABASE_ID` (required for Notion notifications)
- `NOTION_TITLE_PROPERTY` (optional, default `Name`)
- `ALPHAVANTAGE_API_KEY` (required for market data)

## Usage
### CLI
```bash
python -m screener --tickers TICK1,TICK2 --notify discord --interval 1m --top 5
python -m screener --tickers TICK1,TICK2 --notify notion --interval 1m --top 5
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

## Troubleshooting
- **Alpha Vantage missing fields**: floatShares/bid-ask are not provided. The screener estimates float from SharesOutstanding and marks missing data as `推定` in the LLM prompt.
- **Alpha Vantage rate limits**: free tier is limited. The screener retries with backoff, and you should schedule accordingly.
- **Discord length limit**: messages are chunked by paragraph to stay below 2000 characters.
- **Markets closed**: intraday bars may be unavailable. The screener will fall back to recent daily data and label metrics as estimated.

## PR Monitor (Discord通知システム)
`pr_monitor/` に PR監視ボットを追加しました。FMPニュースを監視し、重要度分類・翻訳・Discord Embed通知を行います。

### 構成
- `pr_monitor/pr_monitor.py`: メインループ（`--once`, `--penny`, `--large`, `--ticker`）
- `pr_monitor/classifier.py`: Tier1/Tier2/Tier3 分類
- `pr_monitor/translator.py`: `claude` / `deepl` / `none`
- `pr_monitor/market_data.py`: 株価・時価総額・浮動株取得
- `pr_monitor/discord_sender.py`: Discord Embed送信
- `pr_monitor/config.yaml`: 監視設定
- `pr_monitor/seen_ids.json`: 重複送信防止

### 使い方
```bash
PYTHONPATH=. python pr_monitor/pr_monitor.py --once
PYTHONPATH=. python pr_monitor/pr_monitor.py --penny --once
PYTHONPATH=. python pr_monitor/pr_monitor.py --ticker NVDA --once
```

### 注意
- `translation_engine: claude` を使う場合は `anthropic` パッケージを追加インストールしてください。
- `translation_engine: deepl` は `deepl_api_key` を設定してください。
