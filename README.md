# Statement Normalizer MCP

Deterministic bank-statement parsing for AI agents: messy CSV/OFX exports in, clean categorized ledger rows out.

## Why this exists

Every bank exports transactions differently: shifted headers, inconsistent date formats, debit/credit sign conventions, junk rows. Agents doing bookkeeping either write fragile one-off parsing or hallucinate structure. This server does the boring part correctly, deterministically, and identically every time.

## Privacy posture (read this first)

Your transaction data is processed **in memory only**:

- No storage. Nothing is written to disk or retained after the response
- No external calls. Parsing is pure Python; data never leaves the process
- No LLM in the loop. Deterministic rules, not model inference
- Open source (MIT), so you can verify all of the above, or run it locally and send nothing anywhere

## Tools (4)

- `detect_format(sample)` - identify the export format, delimiter, header row, and date convention
- `normalize_statement(data, format_hint?)` - full parse to clean ledger rows: ISO dates, signed amounts, merchant, category
- `summarize_statement(data)` - totals by category, month, and direction (income/expense)
- `to_quickbooks_csv(data)` - re-emit normalized rows as QuickBooks-importable 3-column CSV

## Example

```
normalize_statement("Date,Description,Amount\n07/03/2026,COFFEE SHOP #42,-4.50\n...")
```

```json
{
  "rows": [
    {"date": "2026-07-03", "description": "COFFEE SHOP #42", "amount": -4.50, "direction": "debit", "category": "dining"}
  ],
  "rows_parsed": 1,
  "rows_skipped": 0,
  "format_detected": "generic_csv_mdy"
}
```

## Run

```bash
pip install "mcp>=2.0"
python server.py          # stdio transport
```

Tests: `python test_server.py` - hand-built fixtures covering CSV variants, OFX, sign conventions, and malformed rows.

## Pricing (hosted)

- Free tier: 50 requests/month (enough to evaluate every tool)
- Then $0.01 per request, metered. Pay only for what you use
- Or run it locally for free, forever (MIT)

## Compliance posture

- Educational and bookkeeping-assist tooling; **not financial advice**
- Deterministic parsing only; no recommendations, no analysis beyond arithmetic totals
- Category assignments are heuristic and user-reviewable, disclosed in-payload

