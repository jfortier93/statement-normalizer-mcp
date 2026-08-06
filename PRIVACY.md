# Privacy Policy — Statement Normalizer MCP

Effective date: 2026-08-06 · Contact: via GitHub issues at https://github.com/jfortier93/statement-normalizer-mcp/issues

## What this service does

Statement Normalizer answers requests for deterministic parsing of the bank statement text you send it, returning normalized rows and totals.

## Data we collect

None, by design.

- Request inputs (statement text, including transaction descriptions and amounts) are processed in memory to compute the response and are not stored by the server.
- The server keeps no database, writes no files, and retains nothing after the response is returned.
- The server makes no external network calls at runtime. Your inputs never leave the process.
- No accounts, cookies, or tracking technologies exist at the server level.

## Hosting and marketplace layer

The hosted endpoint (statement-normalizer.mcpize.run) is served through the MCPize gateway, which manages API keys, metering, and billing. MCPize may process connection metadata (such as API key identity and request counts) under its own terms and privacy policy at https://mcpize.com. We receive aggregate usage counts only; we cannot see your request contents through the marketplace dashboard.

## Self-hosting

The server is MIT-licensed open source. You can run it locally, in which case no third party is involved at all and you can verify every claim above in the source code.

## Data sharing

We do not sell, share, or transfer any user data to third parties. There is none to share.

## Changes

Material changes to this policy will be committed to this repository with a dated entry, so the full history is publicly auditable.

