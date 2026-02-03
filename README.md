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

## Troubleshooting
- **Alpha Vantage missing fields**: floatShares/bid-ask are not provided. The screener estimates float from SharesOutstanding and marks missing data as `推定` in the LLM prompt.
- **Alpha Vantage rate limits**: free tier is limited. The screener retries with backoff, and you should schedule accordingly.
- **Discord length limit**: messages are chunked by paragraph to stay below 2000 characters.
- **Markets closed**: intraday bars may be unavailable. The screener will fall back to recent daily data and label metrics as estimated.
