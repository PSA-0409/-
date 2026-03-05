# Micro-Float Screener

Fully automated micro-float stock screening + risk management with Yahoo Finance, OpenAI Chat Completions, and Discord notifications.

## Features
- Yahoo Finance data collection with retry/backoff and intraday fallbacks (no API key required).
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
- **Yahoo Finance missing fields**: floatShares is provided directly when available. If missing, the screener estimates from SharesOutstanding and marks data as `推定` in the LLM prompt.
- **Yahoo Finance rate limits**: excessive requests may be throttled. The screener retries with backoff, and you should schedule accordingly.
- **Discord length limit**: messages are chunked by paragraph to stay below 2000 characters.
- **Markets closed**: intraday bars may be unavailable. The screener will fall back to recent daily data and label metrics as estimated.
