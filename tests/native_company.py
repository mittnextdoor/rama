"""A small synthetic company kept in a simulated QuickBooks file, for the ledger-native close (docs/100): two months of
books as a bank feed and the client's own invoicing would have put them in the ledger, the bank and card statements for
both months, and a list of mistakes planted in February, written down here before the checks look.

Planted in February (PLANTED): what the checks must find, and what fixes each.
"""
import csv
import io
import json
import os
import tempfile

PLANTED = {
    "missing_line": "HOME DEPOT purchase on the bank statement, not in QuickBooks (create: the ledger booked earlier ones to Materials)",
    "duplicate": "SHELL fuel charge entered twice in QuickBooks; once on the card statement (possible duplicate: a person deletes)",
    "uncategorized": "SHELL fuel charge in Uncategorized Expense (recategorize to Fuel, from the ledger's history)",
    "unknown_line": "ZELLE TO J SMITH on the bank statement, nothing says what it is (waits for a person)",
    "transfer": "a transfer from checking to savings on both statements, in neither ledger account (transfer)",
    "invoice_paid": "a deposit paying open invoice INV-1002 (receive payment)",
    "schedule": "the prepaid insurance schedule's February entry (journal)",
}

ACCOUNTS = [("Checking", "Bank"), ("Savings", "Bank"), ("Visa", "Credit Card"), ("Accounts Receivable (A/R)", "Accounts Receivable"),
            ("Accounts Payable (A/P)", "Accounts Payable"), ("Undeposited Funds", "Other Current Asset"), ("Prepaid Insurance", "Other Current Asset"),
            ("Owner's Equity", "Equity"), ("Retained Earnings", "Equity"), ("Service Revenue", "Income"), ("Materials", "Cost of Goods Sold"),
            ("Fuel", "Expense"), ("Insurance", "Expense"), ("Bank Fees", "Expense"), ("Subcontractors", "Cost of Goods Sold"),
            ("Uncategorized Expense", "Expense")]


def _purchase(acct, to, cents, day, memo, card=False, credit=False):
    d = {"TxnDate": day, "AccountRef": {"name": acct}, "PaymentType": "CreditCard" if card else "Cash", "PrivateNote": memo,
         "Line": [{"Amount": cents / 100, "Description": memo, "DetailType": "AccountBasedExpenseLineDetail",
                   "AccountBasedExpenseLineDetail": {"AccountRef": {"name": to}}}]}
    if credit:
        d["Credit"] = True
    return "Purchase", d


def _deposit(acct, frm, cents, day, memo):
    return "Deposit", {"TxnDate": day, "DepositToAccountRef": {"name": acct}, "PrivateNote": memo,
                       "Line": [{"Amount": cents / 100, "Description": memo, "DetailType": "DepositLineDetail", "DepositLineDetail": {"AccountRef": {"name": frm}}}]}


def _transfer(frm, to, cents, day, memo):
    return "Transfer", {"TxnDate": day, "FromAccountRef": {"name": frm}, "ToAccountRef": {"name": to}, "Amount": cents / 100, "PrivateNote": memo}


def _je(day, memo, lines):
    return "JournalEntry", {"TxnDate": day, "PrivateNote": memo, "Line": [
        {"Amount": abs(c) / 100, "DetailType": "JournalEntryLineDetail",
         "JournalEntryLineDetail": {"PostingType": "Debit" if c > 0 else "Credit", "AccountRef": {"name": a}}} for a, c in lines]}


def _invoice(no, cust, cents, day):
    return "Invoice", {"TxnDate": day, "DocNumber": no, "CustomerRef": {"name": cust}, "DueDate": day,
                       "Line": [{"Amount": cents / 100, "DetailType": "SalesItemLineDetail", "SalesItemLineDetail": {"ItemRef": {"name": "Service"}}}]}


# Messier books (docs/102 step 4), planted in February only with messy=True: the same money in the ledger and on the
# statement that doesn't match as it stands, each put right by changing the client's own entry.
MESSY = {
    "date_drift": "Lopez deposit entered 02/02 in QuickBooks, on the statement 02/10 (redate)",
    "wrong_account": "Staples charge entered in Checking, on the Visa statement (rebank)",
    "undeposited": "two payments waiting in Undeposited Funds, banked as one 750.00 deposit (deposit)",
    "processor_fee": "Square sales deposit of 1,200.00, 1,164.90 arrived (fee line on the deposit)",
    "undeposited_fee": "a 500.00 payment in Undeposited Funds, 485.20 arrived by Stripe (deposit less the fee)",
    "amount_difference": "Ace Hardware 45.90 in QuickBooks, 49.50 on the statement (reamount, a person's word)",
    "check_number": "check 1043 written 01/02, cashed 02/27: matched by its number",
}


# The usual ways a client's own books go wrong (docs/102 step 5), planted in February only with patterns=True.
PATTERNS = {
    "revenue_twice": "Garcia's 1,800.00 deposited to Service Revenue while invoice INV-3001 stays open (a payment applied to it)",
    "bill_paid_as_expense": "Ferguson's 640.00 paid as a Materials expense while bill BL-77 stays open (a bill payment)",
    "card_payment_expensed": "the 500.00 Visa payment from Checking booked to Office Expense (a transfer)",
    "personal_in_business": "Netflix on the Visa in Office Expense, which the owner says is personal (owner's draw)",
    "personal_unrecorded": "a Netflix line on the checking statement, not in QuickBooks (recorded to the owner's draw)",
    "payroll_net": "payroll booked at net: 3,800.00 in Wages, the register says 5,000.00 gross (the withholding moved to Wages)",
}
PERSONAL_RULE = {"id": 901, "pattern": "netflix", "account": "__personal__"}


def _bill(no, vendor, cents, day, acct):
    return "Bill", {"TxnDate": day, "DocNumber": no, "VendorRef": {"name": vendor}, "DueDate": day,
                    "Line": [{"Amount": cents / 100, "DetailType": "AccountBasedExpenseLineDetail",
                              "AccountBasedExpenseLineDetail": {"AccountRef": {"name": acct}}}]}


def _payment(cust, cents, day, invoice_id):
    return "Payment", {"TxnDate": day, "CustomerRef": {"name": cust}, "TotalAmt": cents / 100,
                       "Line": [{"Amount": cents / 100, "LinkedTxn": [{"TxnId": str(invoice_id), "TxnType": "Invoice"}]}]}


def seed(ad, messy=False, patterns=False, cleanup=False, zelles=1):
    """Put the books in the simulated company and return the statement files the bank and card issue: [(name, bytes)]."""
    extra = ([("Merchant Fees", "Expense")] if messy else []) + ([("Office Expense", "Expense"), ("Owner's Draw", "Equity"), ("Wages", "Expense"),
                                                                  ("Payroll Taxes", "Expense"), ("Payroll Liabilities", "Other Current Liability")]
                                                                 if patterns else [])
    for name, typ in ACCOUNTS + extra:
        ad.ensure_account(name, typ)
    ad.ensure_name("Item", "Service", income_account="Service Revenue")
    n = [0]
    stmt = {"1000": [], "1010": [], "2100": []}

    def post(entity_doc, line=None, also=None):
        n[0] += 1
        entity, doc = entity_doc
        tid = ad.create(entity, doc, f"seed-{n[0]}")
        for ref, amount, text in ([line] if line else []) + (also or []):
            stmt[ref].append({"date": doc.get("TxnDate"), "amount": amount, "description": text})
        return tid

    def stmt_only(ref, day, amount, text):
        stmt[ref].append({"date": day, "amount": amount, "description": text})

    post(_je("2025-12-31", "Opening balances", [("Checking", 2000000), ("Prepaid Insurance", 120000), ("Owner's Equity", -2120000)]))
    for m in ("01", "02"):
        y = "2026"
        post(_deposit("Checking", "Service Revenue", 450000, f"{y}-{m}-03", "Customer deposit"), ("1000", 450000, "MOBILE DEPOSIT"))
        post(_purchase("Checking", "Materials", 31250 if m == "01" else 28800, f"{y}-{m}-06", "Home Depot"),
             ("1000", -(31250 if m == "01" else 28800), "POS DBT HOME DEPOT 4471"))
        post(_purchase("Checking", "Materials", 15500, f"{y}-{m}-09", "Home Depot"), ("1000", -15500, "POS DBT HOME DEPOT 4471"))
        post(_purchase("Visa", "Fuel", 8420, f"{y}-{m}-10", "Shell", card=True), ("2100", -8420, "SHELL OIL 57442"))
        post(_purchase("Visa", "Fuel", 7710, f"{y}-{m}-17", "Shell", card=True), ("2100", -7710, "SHELL OIL 57442"))
        post(_purchase("Checking", "Bank Fees", 1500, f"{y}-{m}-28", "Service charge"), ("1000", -1500, "MONTHLY SERVICE FEE"))
        post(_transfer("Checking", "Visa", 16130, f"{y}-{m}-25", "Card payment"), ("1000", -16130, "VISA PAYMENT ONLINE"),
             also=[("2100", 16130, "PAYMENT THANK YOU")])
        if m == "01":
            post(_je("2026-01-31", "NHB schedule INS-1 2026-01", [("Insurance", 10000), ("Prepaid Insurance", -10000)]))
    post(_invoice("INV-1002", "Acme Property", 275000, "2026-01-20"))
    # February's planted mistakes
    stmt_only("1000", "2026-02-12", -22075, "POS DBT HOME DEPOT 4471")                           # missing_line
    post(_purchase("Visa", "Fuel", 9050, "2026-02-14", "Shell", card=True), ("2100", -9050, "SHELL OIL 57442"))
    post(_purchase("Visa", "Fuel", 9050, "2026-02-14", "Shell", card=True))                        # duplicate (no statement line)
    post(_purchase("Visa", "Uncategorized Expense", 6630, "2026-02-21", "SHELL OIL 57442", card=True), ("2100", -6630, "SHELL OIL 57442"))
    stmt_only("1000", "2026-02-18", -40000, "ZELLE TO J SMITH")                                   # unknown_line
    for day, cents in [("2026-02-04", -25000), ("2026-02-11", -30000), ("2026-02-25", -27500)][:max(0, zelles - 1)]:
        stmt_only("1000", day, cents, "ZELLE TO J SMITH")                                         # more like it: one decision for all
    if cleanup:                                                                                    # January isn't right: cleaned up first
        stmt_only("1000", "2026-01-15", -12345, "ADOBE CREATIVE CLD")
    stmt_only("1000", "2026-02-19", -100000, "TRANSFER TO SAV 1010")                              # transfer
    stmt_only("1010", "2026-02-19", 100000, "TRANSFER FROM CHK 1000")
    stmt_only("1000", "2026-02-24", 275000, "DEPOSIT INV-1002 ACME PROPERTY")                     # invoice_paid
    if messy:
        post(_deposit("Checking", "Service Revenue", 65000, "2026-02-02", "Lopez kitchen"))
        stmt_only("1000", "2026-02-10", 65000, "MOBILE DEPOSIT LOPEZ")                              # date_drift
        post(_purchase("Checking", "Materials", 12999, "2026-02-15", "Staples"))
        stmt_only("2100", "2026-02-15", -12999, "STAPLES 0042")                                     # wrong_account
        b = post(_invoice("INV-2001", "Baker Homes", 30000, "2026-02-01"))
        c = post(_invoice("INV-2002", "Chen Dental", 45000, "2026-02-01"))
        post(_payment("Baker Homes", 30000, "2026-02-05", b))
        post(_payment("Chen Dental", 45000, "2026-02-06", c))
        stmt_only("1000", "2026-02-09", 75000, "DEPOSIT")                                           # undeposited
        post(_deposit("Checking", "Service Revenue", 120000, "2026-02-20", "Square sales"))
        stmt_only("1000", "2026-02-21", 116490, "SQUARE INC DEP 260221")                            # processor_fee
        d = post(_invoice("INV-2003", "Dunn Realty", 50000, "2026-02-10"))
        post(_payment("Dunn Realty", 50000, "2026-02-22", d))
        stmt_only("1000", "2026-02-23", 48520, "STRIPE TRANSFER ST-88")                             # undeposited_fee
        post(_purchase("Checking", "Materials", 4590, "2026-02-26", "Ace Hardware"))
        stmt_only("1000", "2026-02-26", -4950, "ACE HARDWARE 118")                                  # amount_difference
        chk = _purchase("Checking", "Subcontractors", 85000, "2026-01-02", "R Diaz")
        chk[1].update(PaymentType="Check", DocNumber="1043")
        post(chk)
        stmt_only("1000", "2026-02-27", -85000, "CHECK 1043")                                       # check_number
    files = []
    if patterns:
        inv = post(_invoice("INV-3001", "Garcia Construction", 180000, "2026-02-03"))
        _ = inv
        post(_deposit("Checking", "Service Revenue", 180000, "2026-02-16", "Garcia Construction"), ("1000", 180000, "DEPOSIT GARCIA"))
        post(_bill("BL-77", "Ferguson Supply", 64000, "2026-02-04", "Materials"))
        post(_purchase("Checking", "Materials", 64000, "2026-02-18", "Ferguson Supply"), ("1000", -64000, "FERGUSON SUPPLY 2231"))
        post(_purchase("Checking", "Office Expense", 50000, "2026-02-26", "Card payment"), ("1000", -50000, "CHASE CARD EPAY"))
        stmt_only("2100", "2026-02-26", 50000, "PAYMENT RECEIVED THANK YOU")
        post(_purchase("Visa", "Office Expense", 1599, "2026-02-11", "NETFLIX.COM", card=True), ("2100", -1599, "NETFLIX.COM"))
        stmt_only("1000", "2026-02-12", -1599, "NETFLIX.COM 866-579")
        post(_purchase("Checking", "Wages", 380000, "2026-02-27", "Gusto net pay"), ("1000", -380000, "GUSTO NET 0227"))
        post(_purchase("Checking", "Payroll Taxes", 158250, "2026-02-27", "Gusto taxes"), ("1000", -158250, "GUSTO TAX 0227"))
        files.append(("2026-02", "payroll_runs_2026-02.csv",
                      b"run_id,date,gross_cents,employee_withheld_cents,employer_burden_cents,net_cents\nPR-0227,2026-02-27,500000,120000,38250,380000\n"))
    if cleanup:                                    # December's statements: the opening balance arrived, and QuickBooks ties there
        files.append(("2025-12", "statement_1000_lines_2025-12.csv",
                      b"line_id,date,account,amount_cents,description\nS1000-12-000,2025-12-31,1000,2000000,OPENING DEPOSIT\n"))
        files.append(("2025-12", "statement_1000_control_2025-12.json", json.dumps(
            {"account": "1000", "coverage_start": "2025-12-01", "coverage_end": "2025-12-31", "opening_cents": 0, "closing_cents": 2000000, "row_count": 1}).encode()))
        files.append(("2025-12", "statement_1010_control_2025-12.json", json.dumps(
            {"account": "1010", "coverage_start": "2025-12-01", "coverage_end": "2025-12-31", "opening_cents": 0, "closing_cents": 0, "row_count": 0}).encode()))
        files.append(("2025-12", "card_statement_2100_control_2025-12.json", json.dumps(
            {"account": "2100", "start": "2025-12-01", "end": "2025-12-31", "opening_liability_cents": 0, "closing_liability_cents": 0}).encode()))
    opening = {"1000": 2000000, "1010": 0, "2100": 0}
    for ref, rows in stmt.items():
        for m in ("01", "02"):
            mine = sorted((r for r in rows if r["date"].startswith(f"2026-{m}")), key=lambda r: r["date"])
            buf = io.StringIO()
            w = csv.writer(buf)
            w.writerow(["line_id", "date", "account", "amount_cents", "description"])
            for i, r in enumerate(mine):
                w.writerow([f"S{ref}-{m}-{i:03d}", r["date"], ref, r["amount"], r["description"]])
            close = opening[ref] + sum(r["amount"] for r in mine)
            if ref == "2100":
                ctl = {"account": ref, "start": f"2026-{m}-01", "end": f"2026-{m}-{'31' if m == '01' else '28'}",
                       "opening_liability_cents": -opening[ref], "closing_liability_cents": -close}
                name = f"card_statement_{ref}_control_2026-{m}.json"
            else:
                ctl = {"account": ref, "coverage_start": f"2026-{m}-01", "coverage_end": f"2026-{m}-{'31' if m == '01' else '28'}",
                       "opening_cents": opening[ref], "closing_cents": close, "row_count": len(mine)}
                name = f"statement_{ref}_control_2026-{m}.json"
            opening[ref] = close
            if mine:
                files.append((f"2026-{m}", f"statement_{ref}_lines_2026-{m}.csv", buf.getvalue().encode()))
            files.append((f"2026-{m}", name, json.dumps(ctl).encode()))
    return files


def build(folder=None, messy=False, patterns=False):
    """(econn, scope, adapter, folder): the books in a simulated company in a fresh engine file, and the statements read
    by the intake from their CSV and JSON files."""
    folder = folder or tempfile.mkdtemp(prefix="nhb-native-")
    os.environ.setdefault("OPS_FILES", os.path.join(folder, "files"))
    from ops import db as edb
    from ops.clientfile import open_client
    from ops.documents import ingest
    from ops.intake.store import convert
    from ops.qbo import SimulatedQBO
    econn = edb.connect(os.path.join(folder, "engine.sqlite3"))
    cid = open_client(econn, code="NAT", legal_name="Native Test Plumbing LLC", entity_type="llc_single", activity="plumbing",
                      cleanup_start="2025-01-01", cleanup_end="2025-12-31", service_start="2026-01-01", systems=[], basis="accrual",
                      synthetic=True, industry="service", intake={"engine": "evidence"}, mode="simulation", actor="test")
    scope = edb.Scope(econn, cid)
    ad = SimulatedQBO(econn, realm="SIM-NAT")
    for month, name, data in seed(ad, messy=messy, patterns=patterns):
        doc, _ = ingest(scope, data, name, "test", meta={"stage": f"{month}/initial"})
        convert(scope, doc)
    return econn, scope, ad, folder


SCHEDULES = [{"key": "INS-1", "label": "Prepaid insurance", "debit": "Insurance", "credit": "Prepaid Insurance", "monthly_cents": 10000}]
ACCOUNT_MAP = {"1000": "Checking", "1010": "Savings", "2100": "Visa"}
