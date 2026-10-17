"""The S&P Capital IQ Pro screen snapshot (licensed: data/capiq/, never committed). One row per company; "NM", "NA",
"NR" and blanks are non-numeric and a rule that needs them skips, it never estimates.

The file is read with the standard library (xlsx is a zip of XML), or from the CSV export of the same sheet."""
import csv
import os
import re
import zipfile
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FOLDER = os.environ.get("RAMA_CAPIQ") or os.path.join(ROOT, "data", "capiq")
SNAPSHOT = "screen_snapshot_2026-10-16"
AS_OF = "2026-10-16"
SOURCE = "S&P Capital IQ Pro screen export, pulled 2026-10-17"
RATINGS_SOURCE = "S&P Global Ratings via S&P Capital IQ Pro"
NUMERIC = ("market_cap_usd_m", "total_debt_usd_m", "cash_st_inv_usd_m", "ebitda_ltm_usd_m", "capex_ltm_usd_m", "net_debt_ebitda_x",
           "ebitda_interest_x")
MISSING = [  # what the screen doesn't have (LEADING_INDICATORS.md, MISSING.md): rules needing these are "not evaluated"
    ("pd_market_signals", "all", "PD Model Market Signals", "not in license"),
    ("credit_scores", "all", "RiskGauge / CreditModel / PD Fundamentals", "not in license"),
    ("ratings_fitch", "all", "Fitch LT issuer rating", "fields returned blank"),
    ("ratings_history", "all", "S&P rating 90 days ago", "not pulled; R3 uses the last action date"),
    ("key_developments", "all", "events", "not pulled; R4 uses one cited event"),
    ("debt_maturities", "CRWV, ORCL", "maturity schedule", "not pulled; R7 uses the fund's own loan maturities"),
    ("equity_prices", "all", "price history", "not pulled; R10 not evaluated"),
    ("financials", "DLR, EQIX", "capex LTM", "returned NA"),
]

_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def _xlsx_rows(path):
    z = zipfile.ZipFile(path)
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", _NS):
            shared.append("".join(t.text or "" for t in si.iter("{%s}t" % _NS["m"])))
    sheet = ET.fromstring(z.read("xl/worksheets/sheet1.xml"))
    rows = []
    for row in sheet.iter("{%s}row" % _NS["m"]):
        cells = {}
        for c in row.findall("m:c", _NS):
            col = re.match(r"[A-Z]+", c.get("r")).group(0)
            v, t = c.find("m:v", _NS), c.get("t")
            if t == "inlineStr":
                val = "".join(x.text or "" for x in c.iter("{%s}t" % _NS["m"]))
            elif v is None:
                val = ""
            elif t == "s":
                val = shared[int(v.text)]
            else:
                val = v.text
            cells[col] = val
        if cells:
            width = max(_col_index(k) for k in cells) + 1
            rows.append([cells.get(_col_name(i), "") for i in range(width)])
    return rows


def _col_index(name):
    n = 0
    for ch in name:
        n = n * 26 + ord(ch) - 64
    return n - 1


def _col_name(i):
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def _num(v):
    v = (v or "").strip()
    if v in ("", "NM", "NA", "NR", "-"):
        return None
    try:
        return float(v)
    except ValueError:
        return None


def path():
    for name in (f"{SNAPSHOT}.xlsx", f"{SNAPSHOT}.csv"):
        p = os.path.join(FOLDER, name)
        if os.path.exists(p):
            return p
    return None


def load():
    """{ticker: row} with numeric fields as floats or None, plus "_raw" flags for NM/NA/NR. Empty dict when no file."""
    p = path()
    if not p:
        return {}
    if p.endswith(".xlsx"):
        table = _xlsx_rows(p)
    else:
        with open(p, newline="", encoding="utf-8-sig") as f:
            table = list(csv.reader(f))
    head = [h.strip() for h in table[0]]
    out = {}
    for raw in table[1:]:
        if not any(raw):
            continue
        row = dict(zip(head, raw + [""] * (len(head) - len(raw))))
        rec = {k: (row.get(k) or "").strip() for k in head}
        rec["_raw"] = {k: rec[k] for k in NUMERIC}
        for k in NUMERIC:
            rec[k] = _num(rec[k])
        out[rec["ticker"]] = rec
    return out


def describe():
    p = path()
    return {"file": os.path.basename(p) if p else None, "present": bool(p), "as_of": AS_OF, "source": SOURCE, "missing": MISSING}
