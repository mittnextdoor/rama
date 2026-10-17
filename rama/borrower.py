"""The synthetic borrower whose month RAMA closes: Helios Compute LLC, a GPU cloud and data-center developer financed by
loan L2 of RAMA Credit Fund I. Its public proxy for market data is CoreWeave (CRWV). Every figure here is synthetic; it is
not CoreWeave's accounting or a claim about its borrowing.

August 2026 is the clean month the books start from; September 2026 is the month closed, with three things wrong the way
real books go wrong:
  1. a power payment on the bank statement that the books never recorded (a known vendor: RAMA records it, citing the line);
  2. September's interest on L2 booked as paid in full in cash, while the bank shows a smaller wire: the borrower's PIK
     election notice explains the gap (part was paid in kind, added to principal). RAMA proposes the split, citing the
     notice and the bank line; a person accepts it;
  3. a small fee on the bank statement nothing supports: it stays an exception in plain sight, never forced to balance.
"""
import csv
import io
import json

from tests import native_company as nc

LEGAL_NAME = "Helios Compute LLC"
CODE = "HELIOS"
PROXY = "CRWV"
LOAN_ID = "L2"
PERIOD = "2026-09"
BOOKS_START = "2026-08-01"
M = 100_000_000                                           # cents in one USD million

OPERATING, RESERVE = "Operating Account", "Debt Service Reserve"
TERM_LOAN = "Term Loan L2 - RAMA Credit Fund I"
VENDOR_LOAN = "GPU Equipment Financing VF1"
ACCOUNT_MAP = {"1000": OPERATING, "1010": RESERVE, "L2": TERM_LOAN, "VF1": VENDOR_LOAN}

ACCOUNTS = [(OPERATING, "Bank"), (RESERVE, "Bank"), ("GPU Equipment", "Fixed Asset"), ("Accumulated Depreciation", "Fixed Asset"),
            ("Data Center Deposits", "Other Current Asset"), (TERM_LOAN, "Long Term Liability"), (VENDOR_LOAN, "Long Term Liability"),
            ("Member's Equity", "Equity"), ("Retained Earnings", "Equity"), ("GPU Cloud Revenue", "Income"), ("Interest Income", "Other Income"),
            ("Power & Cooling", "Cost of Goods Sold"), ("Colocation Rent", "Cost of Goods Sold"), ("Salaries & Benefits", "Expense"),
            ("Network & Software", "Expense"), ("Bank Fees", "Expense"), ("Depreciation", "Expense"), ("Interest Expense", "Expense"),
            ("Interest Expense - PIK", "Expense"), ("Uncategorized Expense", "Expense")]

# who pays the revenue: the statement text -> the tenant and its public proxy (the loan tape's tenant map)
TENANTS = {"HYPERSCALER TENANT A": {"tenant": "Hyperscaler Tenant A", "proxy": "ORCL"},
           "HYPERSCALER TENANT B": {"tenant": "Hyperscaler Tenant B", "proxy": "MSFT"},
           "ENTERPRISE CUSTOMERS": {"tenant": "Enterprise customers", "proxy": None}}

# the depreciation schedule a person approved (straight line on the GPU fleet)
SCHEDULES = [{"key": "DEP-GPU", "label": "GPU fleet depreciation", "debit": "Depreciation", "credit": "Accumulated Depreciation", "monthly_cents": 21 * M}]

# the loan terms that aren't ledger balances (from the credit agreement; synthetic)
LOAN_TERMS = {"loan": LOAN_ID, "lender": "RAMA Credit Fund I", "cash_rate": 0.08, "pik_rate": 0.035, "maturity": "2027-11-30",
              "covenants": {"max_net_debt_ebitda_x": 7.0, "min_ebitda_interest_x": 2.0},
              "collateral": {"type": "GPU fleet (H100-class)", "appraisal_usd_m": 925.0, "appraisal_date": "2025-03-31",
                             "rental_rate_at_appraisal_usd_hr": 4.00, "ltv_at_origination": 0.65, "ltv_covenant": 0.85},
              "origination": "2025-03-31",
              "gp_internal_grade": "performing"}

P, D, TR, JE = nc._purchase, nc._deposit, nc._transfer, nc._je
PIK_MONTH = 175 * M // 100                                # $1.75M a month: 3.5% on $600M, capitalized
CASH_MONTH = 400 * M // 100                               # $4.0M a month: 8% on $600M, wired
FEE_LINE = 1_480_000                                      # $14,800: a fee on the bank statement nothing supports


class Books:
    def __init__(self, ad):
        self.ad, self.n = ad, 0
        self.stmt = {"1000": [], "1010": []}

    def post(self, entity_doc, *lines):
        self.n += 1
        entity, doc = entity_doc
        tid = self.ad.create(entity, doc, f"seed-{self.n}")
        for ref, amount, text in lines:
            self.stmt[ref].append({"date": doc.get("TxnDate"), "amount": amount, "description": text})
        return tid

    def stmt_only(self, ref, day, amount, text):
        self.stmt[ref].append({"date": day, "amount": amount, "description": text})


def _month(b, m, *, plants):
    y = "2026"
    d = lambda day: f"{y}-{m}-{day:02d}"                  # noqa: E731
    b.post(P(OPERATING, "Colocation Rent", 740 * M // 100, d(1), "Northgate Data Centers"), ("1000", -740 * M // 100, "WIRE OUT NORTHGATE DATA CENTERS"))
    b.post(D(OPERATING, "GPU Cloud Revenue", 3480 * M // 100, d(5), "Hyperscaler Tenant A"), ("1000", 3480 * M // 100, "WIRE IN HYPERSCALER TENANT A"))
    b.post(D(OPERATING, "GPU Cloud Revenue", 1740 * M // 100, d(8), "Hyperscaler Tenant B"), ("1000", 1740 * M // 100, "WIRE IN HYPERSCALER TENANT B"))
    b.post(P(OPERATING, "Power & Cooling", 560 * M // 100, d(10), "Gridline Power Co"), ("1000", -560 * M // 100, "ACH PAYMENT GRIDLINE POWER CO"))
    b.post(D(OPERATING, "GPU Cloud Revenue", 580 * M // 100, d(15), "Enterprise customers"), ("1000", 580 * M // 100, "ACH IN ENTERPRISE CUSTOMERS"))
    b.post(P(OPERATING, "Network & Software", 280 * M // 100, d(18), "Zayo Networks"), ("1000", -280 * M // 100, "ACH ZAYO NETWORKS"))
    if "missing_power" in plants:                         # on the bank statement, never recorded
        b.stmt_only("1000", d(24), -560 * M // 100, "ACH PAYMENT GRIDLINE POWER CO")
    else:
        b.post(P(OPERATING, "Power & Cooling", 560 * M // 100, d(24), "Gridline Power Co"), ("1000", -560 * M // 100, "ACH PAYMENT GRIDLINE POWER CO"))
    if m == "09" and "pik_cash_split" in plants:         # booked as paid in full in cash; the bank shows the cash part only
        b.post(P(OPERATING, "Interest Expense", CASH_MONTH + PIK_MONTH, d(25), "RAMA Credit Fund I - L2 September interest"))
        b.stmt_only("1000", d(25), -CASH_MONTH, "WIRE OUT RAMA CREDIT FUND I INT L2")
    else:
        b.post(P(OPERATING, "Interest Expense", CASH_MONTH, d(25), "RAMA Credit Fund I - L2 cash interest"), ("1000", -CASH_MONTH, "WIRE OUT RAMA CREDIT FUND I INT L2"))
    b.post(JE(d(26), "GPU vendor financing VF1: interest and principal", [(VENDOR_LOAN, 25 * M), ("Interest Expense", 833 * M // 100),
                                                                         (OPERATING, -(25 * M + 833 * M // 100))]),
           ("1000", -(25 * M + 833 * M // 100), "WIRE OUT GPU VENDOR FINANCE VF1"))
    b.post(P(OPERATING, "Salaries & Benefits", 460 * M // 100, d(28), "Payroll"), ("1000", -460 * M // 100, "PAYROLL ADP"))
    b.post(P(OPERATING, "Bank Fees", 2500, d(28), "Service charge"), ("1000", -2500, "MONTHLY SERVICE FEE"))
    b.post(D(RESERVE, "Interest Income", 15 * M // 100, d(28), "Reserve interest"), ("1010", 15 * M // 100, "INTEREST CREDIT"))
    if m == "09":
        b.post(TR(OPERATING, RESERVE, 2 * M, d(20), "Debt service reserve top-up"), ("1000", -2 * M, "TRANSFER TO DSR 1010"), ("1010", 2 * M, "TRANSFER FROM OPERATING 1000"))
        if "unknown_wire" in plants:
            b.stmt_only("1000", d(22), -120 * M // 100, "WIRE OUT 4471 ATLAS SUBSTATION SVC")
        if "unknown_fee" in plants:
            b.stmt_only("1000", d(29), -FEE_LINE, "MISC FEE REF 884471")
    last = "31" if m == "08" else "30"
    b.post(JE(f"{y}-{m}-{last}", f"NHB schedule DEP-GPU {y}-{m}", [("Depreciation", 21 * M), ("Accumulated Depreciation", -21 * M)]))
    if not (m == "09" and ("pik_unbooked" in plants or "pik_cash_split" in plants)):
        b.post(JE(f"{y}-{m}-{last}", f"PIK interest capitalized to {TERM_LOAN}", [("Interest Expense - PIK", PIK_MONTH), (TERM_LOAN, -PIK_MONTH)]))


def seed(ad, plants=("missing_power", "pik_cash_split", "unknown_fee")):
    """Put the books in the simulated ledger and return the source files the bank and the lenders issue:
    [(month, filename, bytes)]."""
    for name, typ in ACCOUNTS:
        ad.ensure_account(name, typ)
    b = Books(ad)
    b.post(JE("2026-07-31", "Opening balances", [(OPERATING, 96 * M), (RESERVE, 42 * M), ("GPU Equipment", 3400 * M),
                                                  ("Accumulated Depreciation", -420 * M), ("Data Center Deposits", 35 * M),
                                                  (TERM_LOAN, -600 * M), (VENDOR_LOAN, -2000 * M), ("Member's Equity", -553 * M)]))
    for m in ("08", "09"):
        _month(b, m, plants=plants if m == "09" else ())
    return _files(b)


def _files(b):
    opening = {"1000": 96 * M, "1010": 42 * M}
    files = []
    for ref, rows in b.stmt.items():
        for m, end in (("08", "31"), ("09", "30")):
            mine = sorted((r for r in rows if r["date"].startswith(f"2026-{m}")), key=lambda r: r["date"])
            close = opening[ref] + sum(r["amount"] for r in mine)
            label = f"2026-{m}"
            buf = io.StringIO()
            w = csv.writer(buf)
            w.writerow(["line_id", "date", "account", "amount_cents", "description"])
            for i, r in enumerate(mine):
                w.writerow([f"S{ref}-{m}-{i:03d}", r["date"], ref, r["amount"], r["description"]])
            files.append((label, f"statement_{ref}_lines_{label}.csv", buf.getvalue().encode()))
            files.append((label, f"statement_{ref}_control_{label}.json", json.dumps(
                {"account": ref, "coverage_start": f"2026-{m}-01", "coverage_end": f"2026-{m}-{end}", "opening_cents": opening[ref],
                 "closing_cents": close, "row_count": len(mine)}).encode()))
            opening[ref] = close
    # the lenders' statements: the fund's loan L2 (PIK capitalized monthly) and the GPU vendor's VF1
    l2_open, vf_open, pik_to_date = 600 * M, 2000 * M, 16 * PIK_MONTH     # PIK capitalized since origination (2025-03-31)
    for m, end in (("08", "31"), ("09", "30")):
        label = f"2026-{m}"
        pik_to_date += PIK_MONTH
        rows = [["loan_id", "date", "opening_principal_cents", "principal_paid_cents", "interest_paid_cents", "pik_capitalized_cents",
                 "closing_principal_cents", "pik_capitalized_to_date_cents"],
                ["L2", f"2026-{m}-{end}", l2_open, 0, CASH_MONTH, PIK_MONTH, l2_open + PIK_MONTH, pik_to_date],
                ["VF1", f"2026-{m}-{end}", vf_open, 25 * M, 833 * M // 100, 0, vf_open - 25 * M, 0]]
        buf = io.StringIO()
        csv.writer(buf).writerows(rows)
        files.append((label, f"loan_statement_{label}.csv", buf.getvalue().encode()))
        l2_open, vf_open = l2_open + PIK_MONTH, vf_open - 25 * M
    # the borrower's PIK election notice for September (the evidence that explains the interest split)
    buf = io.StringIO()
    csv.writer(buf).writerows([["loan_id", "period", "election_date", "interest_accrued_cents", "cash_paid_cents", "pik_capitalized_cents", "notice_page"],
                               ["L2", "2026-09", "2026-09-15", CASH_MONTH + PIK_MONTH, CASH_MONTH, PIK_MONTH, 1]])
    files.append(("2026-09", "pik_election_notice_L2_2026-09.csv", buf.getvalue().encode()))
    return files
