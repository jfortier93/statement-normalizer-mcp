"""Statement Normalizer MCP — messy bank CSV/OFX exports -> clean, categorized ledger rows.

Deterministic parsing, zero storage, zero external calls. Educational/bookkeeping
assistance only; verify output before accounting or tax use.
"""
import csv
import datetime
import io
import re

from mcp.server.mcpserver import MCPServer

DISCLAIMER = ("Heuristic normalization and categorization for bookkeeping assistance. "
              "Verify before accounting, tax, or audit use. Data is processed in-memory "
              "only; nothing is stored or transmitted.")

server = MCPServer(
    name="statement-normalizer",
    instructions=("Normalize messy bank statement exports (CSV or OFX/QFX text) into "
                  "clean, categorized, consistently-signed ledger rows. Handles varied "
                  "column names, date formats (US/EU), split debit/credit columns, "
                  "currency symbols, parentheses negatives, decimal commas, junk "
                  "preamble lines, and footer totals. Negative amount = money out."),
)

COLUMN_SYNONYMS = {
    "date": ["date", "transaction date", "posting date", "posted date", "post date",
             "trans date", "value date", "booking date"],
    "description": ["description", "memo", "payee", "name", "details",
                    "transaction details", "narrative", "reference", "merchant"],
    "amount": ["amount", "transaction amount", "amt", "value"],
    "debit": ["debit", "withdrawal", "withdrawals", "money out", "paid out", "debit amount"],
    "credit": ["credit", "deposit", "deposits", "money in", "paid in", "credit amount"],
    "type": ["type", "transaction type", "dr/cr", "cr/dr", "details"],
}

# Ordered: first match wins (e.g. UBER EATS hits dining before UBER hits transport)
CATEGORY_RULES = [
    ("income", ["PAYROLL", "DIRECT DEP", "SALARY", "STRIPE", "CLIENT PAYMENT", "INVOICE",
                "GUSTO", "DEPOSIT FROM"]),
    ("transfers", ["TRANSFER", "XFER", "ZELLE", "VENMO"]),
    ("dining", ["STARBUCKS", "MCDONALD", "CHIPOTLE", "RESTAURANT", "DOORDASH",
                "UBER EATS", "GRUBHUB", "CAFE", "COFFEE"]),
    ("transport_fuel", ["SHELL", "CHEVRON", "EXXON", "UBER", "LYFT", "TFL TRAVEL", "TRANSIT",
                        "PARKING", "FUEL", "AMTRAK"]),
    ("subscriptions_software", ["NETFLIX", "SPOTIFY", "ADOBE", "GITHUB", "OPENAI",
                                "ANTHROPIC", "DROPBOX", "NOTION", "HULU", "SUBSCRIPTION"]),
    ("telecom", ["COMCAST", "VERIZON", "AT&T", "T-MOBILE", "XFINITY", "SPECTRUM"]),
    ("utilities", ["UTILITY", "ELECTRIC", "WATER", "SEWER", "ENERGY"]),
    ("groceries", ["WHOLE FOODS", "TRADER JOE", "KROGER", "SAFEWAY", "ALDI", "TESCO",
                   "GROCERY", "HY-VEE", "PUBLIX"]),
    ("insurance", ["INSURANCE", "GEICO", "ALLSTATE", "PROGRESSIVE"]),
    ("rent_mortgage", ["RENT", "MORTGAGE", "LANDLORD"]),
    ("fees_interest", ["FEE", "INTEREST", "OVERDRAFT", "SERVICE CHARGE"]),
    ("shopping", ["AMAZON", "TARGET", "EBAY", "ETSY", "BEST BUY", "WALMART"]),
    ("health", ["PHARMACY", "CVS", "WALGREEN", "CLINIC", "DENTAL"]),
    ("travel", ["AIRLINE", "DELTA AIR", "HOTEL", "AIRBNB", "MARRIOTT", "SOUTHWEST"]),
    ("taxes", ["IRS TREAS", "TAX PAYMENT", "USTREAS", "US TREASURY"]),
]

DATE_FORMATS = ["%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%m/%d/%y", "%d/%m/%y",
                "%Y/%m/%d", "%d-%m-%Y", "%m-%d-%Y", "%b %d, %Y", "%d %b %Y"]
MDY = {"%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y"}
DMY = {"%d/%m/%Y", "%d/%m/%y", "%d-%m-%Y", "%d %b %Y"}


def _base(payload: dict) -> dict:
    payload["disclaimer"] = DISCLAIMER
    return payload


def _categorize(description: str) -> str:
    up = description.upper()
    for cat, keys in CATEGORY_RULES:
        if any(k in up for k in keys):
            return cat
    return "uncategorized"


def _parse_amount(raw: str):
    s = raw.strip().replace("$", "").replace("\u20ac", "").replace("\u00a3", "").replace(" ", "")
    if not s:
        return None
    neg = False
    up = s.upper()
    if up.endswith("CR"):
        s = s[:-2].strip()
    elif up.endswith("DR"):
        neg, s = True, s[:-2].strip()
    if s.startswith("(") and s.endswith(")"):
        neg, s = True, s[1:-1]
    if s.startswith("-"):
        neg, s = True, s[1:]
    if "." in s and "," in s:
        if s.rindex(",") > s.rindex("."):        # 1.234,56 (EU)
            s = s.replace(".", "").replace(",", ".")
        else:                                     # 1,234.56 (US)
            s = s.replace(",", "")
    elif "," in s:
        head, _, tail = s.rpartition(",")
        if len(tail) == 2:                        # 23,45 -> decimal comma
            s = head.replace(",", "") + "." + tail
        else:                                     # 1,234 -> thousands
            s = s.replace(",", "")
    try:
        val = float(s)
    except ValueError:
        return None
    return -val if neg else val


def _sniff_delimiter(line: str) -> str:
    counts = {d: line.count(d) for d in [",", ";", "\t", "|"]}
    return max(counts, key=counts.get) if max(counts.values()) > 0 else ","


def _detect_header(lines):
    """Return (header_index, delimiter, mapping) for the best-scoring header line."""
    best = (None, ",", {}, 0)
    for i, line in enumerate(lines[:15]):
        if not line.strip():
            continue
        delim = _sniff_delimiter(line)
        cells = [c.strip().strip('"').lower() for c in next(csv.reader([line], delimiter=delim))]
        mapping, score = {}, 0
        for role, syns in COLUMN_SYNONYMS.items():
            for j, cell in enumerate(cells):
                if cell in syns and role not in mapping:
                    mapping[role] = j
        if "date" in mapping:
            score += 2
        if "description" in mapping:
            score += 1
        if "amount" in mapping or ("debit" in mapping and "credit" in mapping):
            score += 2
        if score > best[3]:
            best = (i, delim, mapping, score)
    if best[3] < 4:
        raise ValueError("Could not locate a header row with recognizable date, description, "
                         "and amount (or debit/credit) columns in the first 15 lines.")
    return best[0], best[1], best[2]


def _resolve_date_format(date_strings, date_order: str, warnings: list) -> str:
    totals = {f: sum(1 for d in date_strings if _try(f, d)) for f in DATE_FORMATS}
    full = [f for f, n in totals.items() if n == len(date_strings) and n > 0]
    if full:
        mdy_ok = [f for f in full if f in MDY]
        dmy_ok = [f for f in full if f in DMY]
        if mdy_ok and dmy_ok:
            warnings.append("Date order is ambiguous (all day/month values <= 12); "
                            f"assumed '{date_order}'. Pass date_order='dmy' or 'mdy' to override.")
            return (mdy_ok if date_order == "mdy" else dmy_ok)[0]
        return full[0]
    best = max(totals, key=totals.get)
    if totals[best] == 0:
        raise ValueError("No supported date format matched the date column.")
    return best


def _try(fmt, s):
    try:
        datetime.datetime.strptime(s.strip(), fmt)
        return True
    except (ValueError, TypeError):
        return False


def _parse_csv(text: str, date_order: str, warnings: list):
    lines = text.splitlines()
    header_idx, delim, mapping = _detect_header(lines)
    data_lines = [ln for ln in lines[header_idx + 1:] if ln.strip()]
    rows = list(csv.reader(io.StringIO("\n".join(data_lines)), delimiter=delim))
    date_candidates = [r[mapping["date"]].strip() for r in rows
                       if len(r) > mapping["date"] and r[mapping["date"]].strip()]
    fmt = _resolve_date_format(date_candidates, date_order, warnings)

    parsed, skipped = [], 0
    for r in rows:
        try:
            d = datetime.datetime.strptime(r[mapping["date"]].strip(), fmt).date()
        except (ValueError, IndexError):
            skipped += 1
            continue
        desc = r[mapping["description"]].strip() if "description" in mapping else ""
        if "amount" in mapping:
            amt = _parse_amount(r[mapping["amount"]])
        else:
            deb = _parse_amount(r[mapping["debit"]]) if len(r) > mapping["debit"] else None
            cred = _parse_amount(r[mapping["credit"]]) if len(r) > mapping["credit"] else None
            amt = (cred or 0.0) - abs(deb or 0.0)
            if deb is None and cred is None:
                amt = None
        if amt is None:
            skipped += 1
            continue
        typ = r[mapping["type"]].strip().upper() if "type" in mapping and len(r) > mapping["type"] else ""
        parsed.append({"date": d, "description": desc, "amount": amt, "type": typ})

    # Type-column sign fix: only when no amounts are negative already
    if parsed and all(p["amount"] >= 0 for p in parsed) and any(p["type"] for p in parsed):
        for p in parsed:
            if any(k in p["type"] for k in ("DEBIT", "DR", "WITHDRAW")):
                p["amount"] = -p["amount"]
    if skipped:
        warnings.append(f"Skipped {skipped} line(s) that did not parse as transactions "
                        "(typically footers, totals, or malformed rows).")
    detection = {"input_format": "csv", "delimiter": delim, "header_row_index": header_idx,
                 "column_mapping": mapping, "date_format": fmt,
                 "rows_parsed": len(parsed), "rows_skipped": skipped}
    return parsed, detection


def _parse_ofx(text: str, warnings: list):
    blocks = re.findall(r"<STMTTRN>(.*?)(?=</STMTTRN>|<STMTTRN>|</BANKTRANLIST>|\Z)",
                        text, re.S | re.I)
    parsed, skipped = [], 0
    for b in blocks:
        def field(tag):
            m = re.search(rf"<{tag}>([^<\r\n]+)", b, re.I)
            return m.group(1).strip() if m else ""
        dt, amt = field("DTPOSTED")[:8], _parse_amount(field("TRNAMT"))
        desc = field("NAME") or field("MEMO")
        try:
            d = datetime.datetime.strptime(dt, "%Y%m%d").date()
        except ValueError:
            skipped += 1
            continue
        if amt is None:
            skipped += 1
            continue
        parsed.append({"date": d, "description": desc, "amount": amt,
                       "type": field("TRNTYPE").upper()})
    if skipped:
        warnings.append(f"Skipped {skipped} OFX transaction block(s) with unparseable fields.")
    return parsed, {"input_format": "ofx", "rows_parsed": len(parsed), "rows_skipped": skipped}


def _normalize(statement_text: str, date_order: str, flip_sign: bool):
    warnings: list = []
    if re.search(r"OFXHEADER|<OFX>", statement_text[:2000], re.I):
        parsed, detection = _parse_ofx(statement_text, warnings)
    else:
        parsed, detection = _parse_csv(statement_text, date_order, warnings)
    txns = []
    for p in sorted(parsed, key=lambda x: x["date"]):
        amt = round(-p["amount"] if flip_sign else p["amount"], 2)
        txns.append({
            "date": p["date"].isoformat(),
            "description": re.sub(r"\s+", " ", p["description"]),
            "amount": amt,
            "direction": "out" if amt < 0 else "in",
            "category": _categorize(p["description"]),
        })
    return txns, detection, warnings


# ----------------------------- tools -----------------------------

def normalize_statement(statement_text: str, date_order: str = "mdy",
                        flip_sign: bool = False) -> dict:
    """Normalize a bank statement export (CSV or OFX/QFX text) into clean ledger rows.

    Output rows: ISO date, cleaned description, signed amount (negative = money out),
    direction, heuristic category. date_order ('mdy'|'dmy') resolves ambiguous dates;
    flip_sign=True inverts signs for exports where positive means money out.
    """
    if date_order not in ("mdy", "dmy"):
        raise ValueError("date_order must be 'mdy' or 'dmy'")
    txns, detection, warnings = _normalize(statement_text, date_order, flip_sign)
    return _base({"transactions": txns, "detection": detection, "warnings": warnings})


def detect_format(statement_text: str) -> dict:
    """Report what would be detected (delimiter, header row, column mapping, date format)
    without returning transaction contents. Useful as a cheap pre-flight check."""
    _, detection, warnings = _normalize(statement_text, "mdy", False)
    return _base({"detection": detection, "warnings": warnings})


def to_quickbooks_csv(statement_text: str, date_order: str = "mdy",
                      flip_sign: bool = False) -> dict:
    """Convert a statement export into QuickBooks 3-column import CSV (Date,Description,Amount)."""
    txns, detection, warnings = _normalize(statement_text, date_order, flip_sign)
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(["Date", "Description", "Amount"])
    for t in txns:
        d = datetime.date.fromisoformat(t["date"])
        w.writerow([f"{d.month:02d}/{d.day:02d}/{d.year}", t["description"], f"{t['amount']:.2f}"])
    return _base({"quickbooks_csv": out.getvalue(), "row_count": len(txns),
                  "detection": detection, "warnings": warnings})


def summarize_statement(statement_text: str, date_order: str = "mdy",
                        flip_sign: bool = False) -> dict:
    """Totals for a statement: inflow, outflow, net, by-category breakdown, date range."""
    txns, detection, warnings = _normalize(statement_text, date_order, flip_sign)
    inflow = round(sum(t["amount"] for t in txns if t["amount"] > 0), 2)
    outflow = round(sum(t["amount"] for t in txns if t["amount"] < 0), 2)
    by_cat: dict = {}
    for t in txns:
        by_cat[t["category"]] = round(by_cat.get(t["category"], 0.0) + t["amount"], 2)
    return _base({
        "transaction_count": len(txns),
        "date_range": [txns[0]["date"], txns[-1]["date"]] if txns else None,
        "inflow": inflow, "outflow": outflow, "net": round(inflow + outflow, 2),
        "by_category": by_cat, "detection": detection, "warnings": warnings,
    })


for fn in (normalize_statement, detect_format, to_quickbooks_csv, summarize_statement):
    server.tool()(fn)


if __name__ == "__main__":
    server.run()

