"""Fixture-based tests imitating real bank export chaos. All expected values hand-computed."""
import asyncio
import server as s

def approx(a, b, tol=0.01):
    assert abs(a - b) <= tol, f"expected {b}, got {a}"

# --- Fixture A: US bank, signed amounts, type column, MM/DD/YYYY ---
FIX_A = """Posting Date,Description,Amount,Type,Balance
07/01/2026,ACME PAYROLL DIRECT DEP,2500.00,CREDIT,3120.55
07/02/2026,WHOLE FOODS MARKET #123,-86.43,DEBIT,3034.12
07/03/2026,SHELL OIL 5742,-45.10,DEBIT,2989.02
07/05/2026,NETFLIX.COM,-15.49,DEBIT,2973.53
07/07/2026,TRANSFER TO SAVINGS,-500.00,DEBIT,2473.53
07/13/2026,CITY WATER UTILITY,-60.00,DEBIT,2413.53
"""
r = s.normalize_statement(FIX_A)
t = r["transactions"]
assert len(t) == 6, t
assert r["detection"]["date_format"] == "%m/%d/%Y"   # 07/13 disambiguates
assert t[0] == {"date": "2026-07-01", "description": "ACME PAYROLL DIRECT DEP",
                "amount": 2500.00, "direction": "in", "category": "income"}, t[0]
cats = {x["description"]: x["category"] for x in t}
assert cats["WHOLE FOODS MARKET #123"] == "groceries"
assert cats["SHELL OIL 5742"] == "transport_fuel"
assert cats["NETFLIX.COM"] == "subscriptions_software"
assert cats["TRANSFER TO SAVINGS"] == "transfers"
assert cats["CITY WATER UTILITY"] == "utilities"
summ = s.summarize_statement(FIX_A)
approx(summ["net"], 1792.98)
approx(summ["inflow"], 2500.00)
approx(summ["outflow"], -707.02)

# --- Fixture B: split debit/credit, $ signs, thousands commas, quoted fields ---
FIX_B = '''Date,Description,Debit,Credit,Balance
2026-06-15,"AMAZON MKTPLACE, SEATTLE","$1,234.56",,"$5,000.00"
2026-06-16,PAYPAL INST XFER,45.00,,4955.00
2026-06-20,INTEREST PAYMENT,,$0.55,4955.55
'''
r = s.normalize_statement(FIX_B)
t = r["transactions"]
assert len(t) == 3
approx(t[0]["amount"], -1234.56)
assert t[0]["category"] == "shopping"
approx(t[1]["amount"], -45.00)
assert t[1]["category"] == "transfers"
approx(t[2]["amount"], 0.55)
assert t[2]["category"] == "fees_interest"

# --- Fixture C: European semicolons, DD/MM/YYYY, decimal commas ---
FIX_C = """Booking Date;Details;Amount
15/06/2026;TESCO STORES LONDON;-23,45
16/06/2026;TFL TRAVEL CHARGE;-8,90
17/06/2026;SALARY ACME LTD;2.500,00
"""
r = s.normalize_statement(FIX_C)
t = r["transactions"]
assert r["detection"]["delimiter"] == ";"
assert r["detection"]["date_format"] == "%d/%m/%Y"   # day 15 disambiguates
approx(t[0]["amount"], -23.45)
assert t[0]["category"] == "groceries"
assert t[1]["category"] == "transport_fuel"
approx(t[2]["amount"], 2500.00)
assert t[2]["category"] == "income"

# --- Fixture D: junk preamble + footer total row ---
FIX_D = """Account Statement
Account Number: ****1234
Period: 06/01/2026 - 06/30/2026

Transaction Date,Description,Amount
06/13/2026,STARBUCKS STORE 9921,-6.75
06/14/2026,UBER TRIP HELP.UBER.COM,-18.20
Total,,-24.95
"""
r = s.normalize_statement(FIX_D)
t = r["transactions"]
assert len(t) == 2
assert r["detection"]["header_row_index"] == 4
assert r["detection"]["rows_skipped"] == 1
assert any("Skipped 1" in w for w in r["warnings"])
assert t[0]["category"] == "dining"
assert t[1]["category"] == "transport_fuel"   # UBER (not UBER EATS)

# --- Fixture E: OFX/SGML ---
FIX_E = """OFXHEADER:100
DATA:OFXSGML
<OFX><BANKMSGSRSV1><STMTTRNRS><STMTRS><BANKTRANLIST>
<STMTTRN>
<TRNTYPE>DEBIT
<DTPOSTED>20260705120000
<TRNAMT>-42.50
<NAME>COMCAST CABLE COMM
</STMTTRN>
<STMTTRN>
<TRNTYPE>CREDIT
<DTPOSTED>20260706
<TRNAMT>1500.00
<NAME>CLIENT PAYMENT STRIPE
</STMTTRN>
</BANKTRANLIST></STMTRS></STMTTRNRS></BANKMSGSRSV1></OFX>
"""
r = s.normalize_statement(FIX_E)
t = r["transactions"]
assert r["detection"]["input_format"] == "ofx"
assert len(t) == 2
assert t[0] == {"date": "2026-07-05", "description": "COMCAST CABLE COMM",
                "amount": -42.50, "direction": "out", "category": "telecom"}, t[0]
assert t[1]["category"] == "income"

# --- Fixture F: ambiguous dates -> default mdy + warning; dmy override works ---
FIX_F = """Date,Description,Amount
03/04/2026,COFFEE SHOP,-4.00
05/04/2026,BOOK STORE,-12.00
"""
r = s.normalize_statement(FIX_F)
assert any("ambiguous" in w.lower() for w in r["warnings"])
assert r["transactions"][0]["date"] == "2026-03-04"
r2 = s.normalize_statement(FIX_F, date_order="dmy")
assert r2["transactions"][0]["date"] == "2026-04-03"

# --- flip_sign for credit-card style exports (positive = money out) ---
FIX_G = """Date,Description,Amount
07/13/2026,STARBUCKS STORE 11,6.75
07/14/2026,PAYMENT THANK YOU,-50.00
"""
r = s.normalize_statement(FIX_G, flip_sign=True)
approx(r["transactions"][0]["amount"], -6.75)
approx(r["transactions"][1]["amount"], 50.00)

# --- type-column sign fix when all amounts positive ---
FIX_H = """Date,Description,Amount,Type
07/13/2026,GROCERY OUTLET,55.25,DEBIT
07/14/2026,ACME PAYROLL,900.00,CREDIT
"""
r = s.normalize_statement(FIX_H)
approx(r["transactions"][0]["amount"], -55.25)
approx(r["transactions"][1]["amount"], 900.00)

# --- QuickBooks export ---
qb = s.to_quickbooks_csv(FIX_A)
lines = qb["quickbooks_csv"].splitlines()
assert lines[0] == "Date,Description,Amount"
assert lines[1] == "07/01/2026,ACME PAYROLL DIRECT DEP,2500.00", lines[1]
assert qb["row_count"] == 6

# --- every payload carries the disclaimer; protocol registers all 4 tools ---
for resp in (r, qb, summ):
    assert resp["disclaimer"]
tools = asyncio.run(s.server.list_tools())
names = sorted(x.name for x in tools)
assert names == ["detect_format", "normalize_statement", "summarize_statement",
                 "to_quickbooks_csv"], names
print("ALL TESTS PASSED")
print("Registered tools:", ", ".join(names))

