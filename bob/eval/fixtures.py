"""Synthetic month-end cases for Bob (MONEY TALKS 2): one small service company in a simulated QuickBooks file, January
clean, February with one or more "plants", each a way real books and statements go wrong. Every plant writes down, before
Bob looks, what a careful bookkeeper would expect: the findings Bob must raise on the first read, the changes Bob may make
on its own, the accounts that must tie afterwards, and the exceptions that must stay open for a person.

The expectations are the case author's, kept here and read only by the verifier (bob/eval/expect.py); Bob (bob/engine.py,
ops/native/*) never imports this module. Fixture id: FIXTURE_ID; its version changes whenever a case or an expectation
changes, so two batches are only compared on the same version."""
import csv
import io
import json
import os
import random
import tempfile

from tests import native_company as nc

FIXTURE_ID = "bob-close-synthetic"
FIXTURE_VERSION = "2026-10-17.1"
PERIOD = "2026-02"
BOOKS_START = "2026-01-01"
ACCOUNT_MAP = dict(nc.ACCOUNT_MAP)                        # statement accounts 1000 Checking, 1010 Savings, 2100 Visa
SCHEDULES = [dict(s) for s in nc.SCHEDULES]               # the prepaid insurance schedule a person approved
EXTRA_ACCOUNTS = [("Merchant Fees", "Expense"), ("Office Expense", "Expense"), ("Owner's Draw", "Equity"), ("Wages", "Expense"),
                  ("Payroll Taxes", "Expense"), ("Payroll Liabilities", "Other Current Liability"), ("Interest Income", "Income")]
P = nc._purchase
D = nc._deposit
TR = nc._transfer
JE = nc._je
INV = nc._invoice
BILL = nc._bill
PAY = nc._payment


class Books:
    """The company being built: ledger entries, statement lines per account, extra files, and the case's expectations."""

    def __init__(self, ad):
        self.ad, self.n = ad, 0
        self.stmt = {"1000": [], "1010": [], "2100": []}
        self.files, self.ids = [], {}
        self.schedules = [dict(s) for s in SCHEDULES]
        self.rules = []
        self.shift = {}                                   # statement account -> (opening shift, closing shift) in cents
        self.drop_feb = set()                             # statement accounts whose February statement the client didn't send
        self.replace_feb_with_march = set()               # ... or sent March's instead
        self.dup_lines = []                               # (ref, index in February) statement lines imported twice
        self.expect = {"findings": [], "writes": [], "open": set(), "ties": {"Checking", "Savings", "Visa"}, "difference": {},
                       "model_may_book": set(), "forbid_writes": [], "review": set()}

    def post(self, entity_doc, line=None, also=None, key=None):
        self.n += 1
        entity, doc = entity_doc
        tid = self.ad.create(entity, doc, f"seed-{self.n}")
        for ref, amount, text in ([line] if line else []) + (also or []):
            self.stmt[ref].append({"date": doc.get("TxnDate"), "amount": amount, "description": text})
        if key:
            self.ids[key] = tid
        return tid

    def stmt_only(self, ref, day, amount, text):
        self.stmt[ref].append({"date": day, "amount": amount, "description": text})
        return f"{ref}:{day}:{amount}"

    # ---- expectations
    def finding(self, check, **fields):
        self.expect["findings"].append({"check": check, **fields})

    def write(self, kind):
        self.expect["writes"].append(kind)

    def open(self, *checks):
        self.expect["open"].update(checks)

    def review(self, *checks):
        self.expect["review"].update(checks)

    def no_tie(self, account, difference=None):
        self.expect["ties"].discard(account)
        if difference is not None:
            self.expect["difference"][account] = difference


def base(b):
    """January and February as the bank feed and the client's own invoicing would have put them: clean."""
    for name, typ in nc.ACCOUNTS + EXTRA_ACCOUNTS:
        b.ad.ensure_account(name, typ)
    b.ad.ensure_name("Item", "Service", income_account="Service Revenue")
    b.post(JE("2025-12-31", "Opening balances", [("Checking", 2000000), ("Prepaid Insurance", 120000), ("Owner's Equity", -2120000)]))
    for m in ("01", "02"):
        y = "2026"
        b.post(D("Checking", "Service Revenue", 450000, f"{y}-{m}-03", "Customer deposit"), ("1000", 450000, "MOBILE DEPOSIT"))
        b.post(P("Checking", "Materials", 31250 if m == "01" else 28800, f"{y}-{m}-06", "Home Depot"), ("1000", -(31250 if m == "01" else 28800), "POS DBT HOME DEPOT 4471"))
        b.post(P("Checking", "Materials", 15500, f"{y}-{m}-09", "Home Depot"), ("1000", -15500, "POS DBT HOME DEPOT 4471"))
        b.post(P("Visa", "Fuel", 8420, f"{y}-{m}-10", "Shell", card=True), ("2100", -8420, "SHELL OIL 57442"))
        b.post(P("Visa", "Fuel", 7710, f"{y}-{m}-17", "Shell", card=True), ("2100", -7710, "SHELL OIL 57442"))
        b.post(P("Checking", "Bank Fees", 1500, f"{y}-{m}-28", "Service charge"), ("1000", -1500, "MONTHLY SERVICE FEE"), key=f"fee-{m}")
        b.post(TR("Checking", "Visa", 16130, f"{y}-{m}-25", "Card payment"), ("1000", -16130, "VISA PAYMENT ONLINE"), also=[("2100", 16130, "PAYMENT THANK YOU")])
        b.post(JE(f"{y}-{m}-{'31' if m == '01' else '28'}", f"NHB schedule INS-1 {y}-{m}", [("Insurance", 10000), ("Prepaid Insurance", -10000)]), key=f"sched-{m}")
    b.post(INV("INV-1002", "Acme Property", 275000, "2026-01-20"), key="inv-1002")


# ------------------------------------------------------------------ the plants
def clean(b):
    """Nothing wrong: Bob must change nothing and raise no blocker."""


def missing_known_vendor(b):
    """A Home Depot line on the statement, not in QuickBooks; January booked the same vendor to Materials."""
    b.stmt_only("1000", "2026-02-12", -22075, "POS DBT HOME DEPOT 4471")
    b.finding("unrecorded", kind="create", to="Materials", auto=True)
    b.write("create")


def missing_unknown_payee(b):
    """A Zelle to a person nothing explains: Bob asks, never guesses."""
    b.stmt_only("1000", "2026-02-18", -40000, "ZELLE TO J SMITH")
    b.finding("unrecorded", kind="create", to=None, auto=False, who="reviewer")
    b.open("unrecorded")
    b.expect["model_may_book"].add("ZELLE TO J SMITH")


def duplicate_entry(b):
    """The same fuel charge entered twice in QuickBooks; the card statement shows it once."""
    b.post(P("Visa", "Fuel", 9050, "2026-02-14", "Shell", card=True), ("2100", -9050, "SHELL OIL 57442"))
    b.post(P("Visa", "Fuel", 9050, "2026-02-14", "Shell", card=True))
    b.finding("possible_duplicate", kind="delete", auto=False)
    b.open("possible_duplicate")


def uncategorized_fuel(b):
    b.post(P("Visa", "Uncategorized Expense", 6630, "2026-02-21", "SHELL OIL 57442", card=True), ("2100", -6630, "SHELL OIL 57442"))
    b.finding("uncategorized", kind="recategorize", to="Fuel", auto=True)
    b.write("recategorize")


def transfer_unrecorded(b):
    b.stmt_only("1000", "2026-02-19", -100000, "TRANSFER TO SAV 1010")
    b.stmt_only("1010", "2026-02-19", 100000, "TRANSFER FROM CHK 1000")
    b.finding("unrecorded", kind="transfer", auto=True)
    b.write("transfer")


def invoice_payment_named(b):
    """The deposit names the open invoice: Bob applies it."""
    b.stmt_only("1000", "2026-02-24", 275000, "DEPOSIT INV-1002 ACME PROPERTY")
    b.finding("unrecorded", kind="receive", auto=True)
    b.write("receive")


def invoice_payment_unnamed(b):
    """A deposit for exactly the open invoice's amount, naming nothing: a person confirms."""
    b.stmt_only("1000", "2026-02-24", 275000, "MOBILE DEPOSIT")
    b.finding("unrecorded", kind="receive", auto=False)
    b.open("unrecorded")


def partial_invoice_payment(b):
    """A customer pays part of an open invoice. It isn't new revenue: it's a receivable coming in, and a person decides
    how to apply it. Bob must not book it to Service Revenue on its own."""
    b.stmt_only("1000", "2026-02-24", 100000, "DEPOSIT ACME PROPERTY")
    b.finding("unrecorded")
    b.expect["forbid_writes"].append({"kind": "create", "to": "Service Revenue", "description": "DEPOSIT ACME PROPERTY"})
    b.open("unrecorded")
    b.expect["model_may_book"].add("DEPOSIT ACME PROPERTY")


def schedule_missing(b):
    """February's prepaid insurance entry wasn't booked."""
    b.ad.delete("JournalEntry", b.ids["sched-02"])
    b.finding("schedule_entry", kind="journal", auto=True)
    b.write("journal")


def processor_fee(b):
    """Square's deposit arrived net of its fee."""
    b.post(D("Checking", "Service Revenue", 120000, "2026-02-20", "Square sales"))
    b.stmt_only("1000", "2026-02-21", 116490, "SQUARE INC DEP 260221")
    b.finding("processor_fee", kind="fee", auto=True)
    b.write("fee")


def undeposited_two_payments(b):
    i1 = b.post(INV("INV-2001", "Baker Homes", 30000, "2026-02-01"))
    i2 = b.post(INV("INV-2002", "Chen Dental", 45000, "2026-02-01"))
    b.post(PAY("Baker Homes", 30000, "2026-02-05", i1))
    b.post(PAY("Chen Dental", 45000, "2026-02-06", i2))
    b.stmt_only("1000", "2026-02-09", 75000, "DEPOSIT")
    b.finding("undeposited", kind="deposit", auto=True)
    b.write("deposit")


def undeposited_net_of_fee(b):
    i = b.post(INV("INV-2003", "Dunn Realty", 50000, "2026-02-10"))
    b.post(PAY("Dunn Realty", 50000, "2026-02-22", i))
    b.stmt_only("1000", "2026-02-23", 48520, "STRIPE TRANSFER ST-88")
    b.finding("undeposited", kind="deposit", auto=True)
    b.write("deposit")


def refund_unrecorded(b):
    """A return at Home Depot credited to the card; QuickBooks doesn't have it. The refund reduces Materials."""
    b.stmt_only("2100", "2026-02-19", 4500, "HOME DEPOT RETURN 4471")
    b.finding("unrecorded", kind="create", to="Materials", auto=True)
    b.write("create")


def refund_unrecorded_fuel(b):
    """A fuel refund onto the card (a disputed charge reversed): Shell is in the ledger's history, to Fuel."""
    b.stmt_only("2100", "2026-02-22", 7710, "SHELL OIL 57442 REFUND")
    b.finding("unrecorded", kind="create", to="Fuel", auto=True)
    b.write("create")


def vendor_description_varies(b):
    """The same vendor, described differently by the bank this month (an online order): the books' history still says
    where it goes."""
    b.stmt_only("1000", "2026-02-13", -18900, "HOME DEPOT ONLINE 4471")
    b.finding("unrecorded", kind="create", to="Materials", auto=True)
    b.write("create")


def refund_recorded(b):
    """The same return, recorded in QuickBooks as a card credit: it simply matches."""
    b.post(P("Visa", "Materials", 4500, "2026-02-19", "Home Depot return", card=True, credit=True), ("2100", 4500, "HOME DEPOT RETURN 4471"))


def outstanding_check(b):
    """A check written late in February, not yet cashed: outstanding, not a problem."""
    chk = P("Checking", "Subcontractors", 60000, "2026-02-26", "R Diaz")
    chk[1].update(PaymentType="Check", DocNumber="1051")
    b.post(chk)


def deposit_in_transit(b):
    """A deposit recorded on the 28th that the bank shows in March."""
    b.post(D("Checking", "Service Revenue", 32000, "2026-02-28", "Late deposit"))


def stale_check(b):
    """A check from early January that never cleared: a person looks at it; it doesn't break the tie."""
    chk = P("Checking", "Subcontractors", 12500, "2026-01-05", "M Ortiz")
    chk[1].update(PaymentType="Check", DocNumber="1041")
    b.post(chk)
    b.finding("not_on_statement")
    b.review("not_on_statement")


def duplicate_import(b):
    """The bank feed's file carries one February line twice (an import run twice). The statement's closing balance is the
    bank's, so the lines don't foot; the second copy is no transaction and Bob must not record one for it."""
    b.dup_lines.append(("1000", "POS DBT HOME DEPOT 4471"))
    b.finding("statement_incomplete")
    b.expect["forbid_writes"].append({"kind": "create", "description": "POS DBT HOME DEPOT 4471"})
    b.open("statement_incomplete")


def duplicate_import_card(b):
    """The card feed's file carries a fuel charge twice."""
    b.dup_lines.append(("2100", "SHELL OIL 57442"))
    b.finding("statement_incomplete")
    b.expect["forbid_writes"].append({"kind": "create", "description": "SHELL OIL 57442"})
    b.open("statement_incomplete")


def duplicate_import_fee(b):
    """The checking file carries the service charge twice."""
    b.dup_lines.append(("1000", "MONTHLY SERVICE FEE"))
    b.finding("statement_incomplete")
    b.expect["forbid_writes"].append({"kind": "create", "description": "MONTHLY SERVICE FEE"})
    b.open("statement_incomplete")
    b.expect["model_may_book"].add("MONTHLY SERVICE FEE")


def missing_support_prepaid(b):
    """A prepaid balance with no schedule behind it: unsupported until a person says what it is."""
    b.schedules.clear()
    b.ad.delete("JournalEntry", b.ids["sched-02"])
    b.finding("unsupported_balance")
    b.review("unsupported_balance")


def wrong_period_statement(b):
    """The client sent March's checking statement instead of February's."""
    b.replace_feb_with_march.add("1000")
    b.finding("statement_missing", who="client")
    b.open("statement_missing")
    b.no_tie("Checking")


def opening_balance_discrepancy(b):
    """The February statement opens 100.00 below January's closing (the bank took a fee January's file didn't show):
    the account doesn't reconcile, and Bob must say so rather than make it balance."""
    b.shift["1000"] = (-10000, -10000)
    b.finding("reconciliation_difference")
    b.open("reconciliation_difference")
    b.no_tie("Checking", difference=10000)                # the books hold 100.00 the bank doesn't (difference = books - bank)


def amount_difference(b):
    """Two digits swapped when the receipt was typed: the amount is corrected on a person's word."""
    b.post(P("Checking", "Materials", 4590, "2026-02-26", "Ace Hardware"))
    b.stmt_only("1000", "2026-02-26", -4950, "ACE HARDWARE 118")
    b.finding("amount_difference", kind="reamount", auto=False)
    b.open("amount_difference")


def wrong_bank_account(b):
    b.post(P("Checking", "Materials", 12999, "2026-02-15", "Staples"))
    b.stmt_only("2100", "2026-02-15", -12999, "STAPLES 0042")
    b.finding("wrong_account", kind="rebank", auto=True)
    b.write("rebank")


def date_drift(b):
    b.post(D("Checking", "Service Revenue", 65000, "2026-02-02", "Lopez kitchen"))
    b.stmt_only("1000", "2026-02-10", 65000, "MOBILE DEPOSIT LOPEZ")
    b.finding("date_drift", kind="redate", auto=True)
    b.write("redate")


def check_number_match(b):
    """A January check cashed in late February: matched by its number, nothing to raise."""
    chk = P("Checking", "Subcontractors", 85000, "2026-01-02", "R Diaz")
    chk[1].update(PaymentType="Check", DocNumber="1043")
    b.post(chk)
    b.stmt_only("1000", "2026-02-27", -85000, "CHECK 1043")


def bank_fee_unrecorded(b):
    """February's service charge isn't in QuickBooks. January's was, to Bank Fees, but once: the engine's rule is at least
    two earlier lines to one account before it books a line itself, so this one is a person's (or the model's, cited)."""
    b.ad.delete("Purchase", b.ids["fee-02"])
    b.finding("unrecorded", kind="create", to=None, auto=False)
    b.open("unrecorded")
    b.expect["model_may_book"].add("MONTHLY SERVICE FEE")


def card_payment_missing(b):
    """A second card payment on both statements and in neither register."""
    b.stmt_only("1000", "2026-02-27", -20000, "VISA PAYMENT ONLINE")
    b.stmt_only("2100", "2026-02-27", 20000, "PAYMENT THANK YOU")
    b.finding("unrecorded", kind="transfer", auto=True)
    b.write("transfer")


def revenue_twice(b):
    b.post(INV("INV-3001", "Garcia Construction", 180000, "2026-02-03"))
    b.post(D("Checking", "Service Revenue", 180000, "2026-02-16", "Garcia Construction"), ("1000", 180000, "DEPOSIT GARCIA"))
    b.finding("revenue_twice", kind="replace", auto=False)
    b.open("revenue_twice")


def bill_paid_as_expense(b):
    b.post(BILL("BL-77", "Ferguson Supply", 64000, "2026-02-04", "Materials"))
    b.post(P("Checking", "Materials", 64000, "2026-02-18", "Ferguson Supply"), ("1000", -64000, "FERGUSON SUPPLY 2231"))
    b.finding("bill_paid_as_expense", kind="replace", auto=False)
    b.open("bill_paid_as_expense")


def card_payment_expensed(b):
    b.post(P("Checking", "Office Expense", 50000, "2026-02-26", "Card payment"), ("1000", -50000, "CHASE CARD EPAY"))
    b.stmt_only("2100", "2026-02-26", 50000, "PAYMENT RECEIVED THANK YOU")
    b.finding("card_payment_expensed", kind="replace", auto=False)
    b.open("card_payment_expensed")


def personal_in_business(b):
    """Netflix on the business card, booked to Office Expense; the owner's standing instruction says Netflix is personal."""
    b.rules.append(dict(nc.PERSONAL_RULE))
    b.post(P("Visa", "Office Expense", 1599, "2026-02-11", "NETFLIX.COM", card=True), ("2100", -1599, "NETFLIX.COM"))
    b.finding("personal_in_business", kind="recategorize", to="Owner's Draw", auto=True)
    b.write("recategorize")


def personal_unrecorded(b):
    b.rules.append(dict(nc.PERSONAL_RULE))
    b.stmt_only("1000", "2026-02-12", -1599, "NETFLIX.COM 866-579")
    b.finding("unrecorded", kind="create", to="Owner's Draw", auto=True)
    b.write("create")


def payroll_net(b):
    b.post(P("Checking", "Wages", 380000, "2026-02-27", "Gusto net pay"), ("1000", -380000, "GUSTO NET 0227"))
    b.post(P("Checking", "Payroll Taxes", 158250, "2026-02-27", "Gusto taxes"), ("1000", -158250, "GUSTO TAX 0227"))
    b.files.append(("2026-02", "payroll_runs_2026-02.csv",
                    b"run_id,date,gross_cents,employee_withheld_cents,employer_burden_cents,net_cents\nPR-0227,2026-02-27,500000,120000,38250,380000\n"))
    b.finding("payroll_net", kind="journal", auto=False)
    b.open("payroll_net")


def interest_unexplained(b):
    """Interest on savings, the first ever: nothing in the books says where it goes."""
    b.stmt_only("1010", "2026-02-28", 42, "INTEREST PAID")
    b.finding("unrecorded", kind="create", auto=False)
    b.open("unrecorded")
    b.expect["model_may_book"].add("INTEREST PAID")


def savings_statement_missing(b):
    """The transfer shows on checking; savings' statement never came."""
    b.stmt_only("1000", "2026-02-19", -100000, "TRANSFER TO SAV 1010")
    b.drop_feb.add("1010")
    b.finding("statement_missing", who="client")
    b.finding("unrecorded", kind="create", auto=False)
    b.open("statement_missing", "unrecorded")
    b.no_tie("Savings")
    b.expect["model_may_book"].add("TRANSFER TO SAV 1010")


PLANTS = {f.__name__: f for f in (clean, missing_known_vendor, missing_unknown_payee, duplicate_entry, uncategorized_fuel, transfer_unrecorded,
                                  invoice_payment_named, invoice_payment_unnamed, partial_invoice_payment, schedule_missing, processor_fee,
                                  undeposited_two_payments, undeposited_net_of_fee, refund_unrecorded, refund_unrecorded_fuel, vendor_description_varies,
                                  refund_recorded, outstanding_check, deposit_in_transit, stale_check, duplicate_import, duplicate_import_card,
                                  duplicate_import_fee, missing_support_prepaid, wrong_period_statement,
                                  opening_balance_discrepancy, amount_difference, wrong_bank_account, date_drift, check_number_match,
                                  bank_fee_unrecorded, card_payment_missing, revenue_twice, bill_paid_as_expense, card_payment_expensed,
                                  personal_in_business, personal_unrecorded, payroll_net, interest_unexplained, savings_statement_missing)}
# plants that can't share a case: they touch the same money, or one's expectation hides the other's
CONFLICTS = [{"invoice_payment_named", "invoice_payment_unnamed", "partial_invoice_payment"}, {"refund_unrecorded", "refund_recorded"},
             {"duplicate_import", "duplicate_import_card", "duplicate_import_fee"}, {"duplicate_import_card", "duplicate_entry", "uncategorized_fuel", "refund_unrecorded_fuel"},
             {"duplicate_import_fee", "bank_fee_unrecorded"}, {"vendor_description_varies", "duplicate_import"},
             {"wrong_period_statement", "opening_balance_discrepancy", "duplicate_import", "duplicate_import_fee"},
             {"schedule_missing", "missing_support_prepaid"}, {"transfer_unrecorded", "savings_statement_missing"},
             {"personal_in_business", "personal_unrecorded"}, {"card_payment_missing", "card_payment_expensed"},
             {"savings_statement_missing", "interest_unexplained"}, {"duplicate_entry", "uncategorized_fuel"}]
# these break checking's tie on purpose, so they never share a case with another plant on checking
CHECKING_BREAKERS = {"wrong_period_statement", "opening_balance_discrepancy", "duplicate_import", "duplicate_import_fee"}
CHECKING_PLANTS = {"missing_known_vendor", "missing_unknown_payee", "transfer_unrecorded", "invoice_payment_named", "invoice_payment_unnamed",
                   "partial_invoice_payment", "processor_fee", "undeposited_two_payments", "undeposited_net_of_fee", "outstanding_check",
                   "deposit_in_transit", "stale_check", "amount_difference", "wrong_bank_account", "date_drift", "check_number_match",
                   "bank_fee_unrecorded", "card_payment_missing", "revenue_twice", "bill_paid_as_expense", "card_payment_expensed",
                   "personal_unrecorded", "payroll_net", "savings_statement_missing", "vendor_description_varies"} | CHECKING_BREAKERS


def compatible(names):
    s = set(names)
    if any(len(s & g) > 1 for g in CONFLICTS):
        return False
    if s & CHECKING_BREAKERS and (s - CHECKING_BREAKERS) & CHECKING_PLANTS:
        return False
    return True


def cases():
    """The case list: every plant alone, then combinations drawn with a fixed seed (the same list every run)."""
    out = [{"id": f"single-{n}", "plants": [n]} for n in PLANTS]
    rng = random.Random(20261017)
    names = [n for n in PLANTS if n != "clean"]
    seen = {tuple(c["plants"]) for c in out}
    while len(out) < 72:
        k = rng.choice([2, 2, 3])
        pick = tuple(sorted(rng.sample(names, k)))
        if pick in seen or not compatible(pick):
            continue
        seen.add(pick)
        out.append({"id": f"combo-{len(out) - len(PLANTS) + 1:02d}-" + "+".join(pick), "plants": list(pick)})
    return out


# ------------------------------------------------------------------ building one case
def _statements(b):
    """The statement files the bank and card issue for January and February, as the intake reads them."""
    opening = {"1000": 2000000, "1010": 0, "2100": 0}
    files = []
    for ref, rows in b.stmt.items():
        for m in ("01", "02"):
            mine = sorted((r for r in rows if r["date"].startswith(f"2026-{m}")), key=lambda r: r["date"])
            true_close = opening[ref] + sum(r["amount"] for r in mine)
            op, close, label, start, end = opening[ref], true_close, f"2026-{m}", f"2026-{m}-01", f"2026-{m}-{'31' if m == '01' else '28'}"
            opening[ref] = true_close
            if m == "02":
                if ref in b.drop_feb:                     # the client never sent it
                    continue
                if ref in b.shift:                        # the bank's balances differ from what the ledger expects
                    op, close = op + b.shift[ref][0], close + b.shift[ref][1]
                for dref, text in b.dup_lines:            # a line imported twice; the balances are the bank's
                    if dref == ref:
                        twin = next((r for r in mine if r["description"] == text), None)
                        if twin:
                            mine = sorted(mine + [dict(twin)], key=lambda r: r["date"])
                if ref in b.replace_feb_with_march:       # March's statement in place of February's
                    mine, label, start, end, op = [], "2026-03", "2026-03-01", "2026-03-31", close
            buf = io.StringIO()
            w = csv.writer(buf)
            w.writerow(["line_id", "date", "account", "amount_cents", "description"])
            for i, r in enumerate(mine):
                w.writerow([f"S{ref}-{label[-2:]}-{i:03d}", r["date"], ref, r["amount"], r["description"]])
            if ref == "2100":
                ctl = {"account": ref, "start": start, "end": end, "opening_liability_cents": -op, "closing_liability_cents": -close}
                name = f"card_statement_{ref}_control_{label}.json"
            else:
                ctl = {"account": ref, "coverage_start": start, "coverage_end": end, "opening_cents": op, "closing_cents": close, "row_count": len(mine)}
                name = f"statement_{ref}_control_{label}.json"
            if mine:
                files.append((label, f"statement_{ref}_lines_{label}.csv", buf.getvalue().encode()))
            files.append((label, name, json.dumps(ctl).encode()))
    return files


def build(case, folder=None):
    """(econn, scope, adapter, inputs, expectations, folder): the case's books in a fresh simulated company and engine
    file, its statements read by the intake. inputs is what Bob is given; expectations is what only the verifier sees."""
    folder = folder or tempfile.mkdtemp(prefix="bob-case-")
    os.environ["OPS_FILES"] = os.path.join(folder, "files")
    from ops import db as edb
    from ops.clientfile import open_client
    from ops.documents import ingest
    from ops.intake.store import convert
    from ops.qbo import SimulatedQBO
    econn = edb.connect(os.path.join(folder, "engine.sqlite3"))
    cid = open_client(econn, code="BOB", legal_name="Bob Demo Plumbing LLC", entity_type="llc_single", activity="plumbing",
                      cleanup_start="2025-01-01", cleanup_end="2025-12-31", service_start="2026-01-01", systems=[], basis="accrual",
                      synthetic=True, industry="service", intake={"engine": "evidence"}, mode="simulation", actor="bob-eval")
    scope = edb.Scope(econn, cid)
    ad = SimulatedQBO(econn, realm=f"SIM-{case['id'][:20]}")
    b = Books(ad)
    base(b)
    for name in case["plants"]:
        PLANTS[name](b)
    for month, name, data in _statements(b) + b.files:
        doc, _ = ingest(scope, data, name, "bob-eval", meta={"stage": f"{month}/initial"})
        convert(scope, doc)
    inputs = {"period": PERIOD, "account_map": ACCOUNT_MAP, "schedules": b.schedules, "rules": b.rules, "books_start": BOOKS_START}
    exp = dict(b.expect, ties=sorted(b.expect["ties"]), open=sorted(b.expect["open"]), review=sorted(b.expect["review"]),
               model_may_book=sorted(b.expect["model_may_book"]))
    return econn, scope, ad, inputs, exp, folder


def source_package(case):
    """The case's statement and payroll files alone (for loading into the product as a client's upload), plus its books
    as a function that seeds a simulated company: (seed(adapter) -> files, inputs)."""
    def seed(ad):
        b = Books(ad)
        base(b)
        for name in case["plants"]:
            PLANTS[name](b)
        return _statements(b) + b.files, {"schedules": b.schedules, "rules": b.rules}
    return seed
