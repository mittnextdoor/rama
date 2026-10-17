"""QuickBooks Online boundary. Two adapters with one interface:

SimulatedQBO  a double-entry company inside the ops database (tables sim_qbo_*). Development, tests and the demo.
              SIMULATED: nothing leaves this machine.
LiveQBO       Intuit Accounting API v3 (sandbox or real company). VERIFIED against an Intuit sandbox on 2026-09-27:
              `python3 -m ops sandbox-rehearsal` passed every check, including requestid recovery after a dropped
              response (docs/49 §9). Real companies also need production keys and the owner's approval (mode 'execute'). Behaviour it relies on,
              from Intuit's documentation: create calls accept a `requestid` query parameter, and a repeated requestid
              returns the original response instead of creating a duplicate; throttling is 500 requests/minute and
              10 concurrent per company (HTTP 429: retry with the same requestid); updates need the current SyncToken.

What the API can do here: create accounts, Purchases (expenses and card charges/credits), Deposits, Transfers and
JournalEntries; attach documents (Attachable); read reports (ProfitAndLoss, BalanceSheet, GeneralLedger/TransactionList).
What it can't: complete a bank reconciliation, accept or match "For Review" bank-feed items, connect bank feeds or
create the client's company. Those stay manual steps in the QuickBooks screens (see docs/49 §4).

Amounts inside this module: integer cents, debit-positive for ledger lines.
"""
import json
import time
import urllib.error
import urllib.parse
import urllib.request

ACCOUNT_TYPES = {  # our COA type -> (QBO AccountType, natural sign: +1 debit-normal)
    "Bank": ("Bank", 1), "Credit Card": ("Credit Card", -1), "Long Term Liability": ("Long Term Liability", -1),
    "Other Current Asset": ("Other Current Asset", 1), "Fixed Asset": ("Fixed Asset", 1), "Equity": ("Equity", -1),
    "Other Current Liability": ("Other Current Liability", -1),
    "Income": ("Income", -1), "Other Income": ("Other Income", -1), "Cost of Goods Sold": ("Cost of Goods Sold", 1),
    "Expense": ("Expense", 1), "Accounts Receivable": ("Accounts Receivable", 1), "Accounts Payable": ("Accounts Payable", -1),
}

# QuickBooks requires an AccountSubType for some account types (Fixed Asset is rejected without one, found in the
# sandbox run); balance-sheet accounts always get one. Income and expense accounts take QuickBooks' default.
SUBTYPES = {"Bank": "Checking", "Credit Card": "CreditCard", "Long Term Liability": "NotesPayable",
            "Other Current Asset": "OtherCurrentAssets", "Fixed Asset": "MachineryAndEquipment", "Equity": "OwnersEquity",
            "Other Current Liability": "OtherCurrentLiabilities", "Accounts Receivable": "AccountsReceivable",
            "Accounts Payable": "AccountsPayable"}
SUBTYPE_BY_NAME = {"Savings": "Savings", "Buildings": "Buildings", "Land": "Land", "Furniture Fixtures and Equipment": "FurnitureAndFixtures", "Accumulated Depreciation": "OtherFixedAssets"}   # QuickBooks only allows its AccumulatedDepreciation subtype under a parent asset


class QBOError(Exception):
    def __init__(self, msg, *, uncertain=False, status=None):
        super().__init__(msg)
        self.uncertain, self.status = uncertain, status


UNDEPOSITED = "Undeposited Funds"                         # QuickBooks' own account for payments received, not yet banked


def ledger_lines(entity, doc, items=None, ar="Accounts Receivable (A/R)", ap="Accounts Payable (A/P)"):
    """Debit-positive ledger lines (account, cents, memo) implied by a QBO-style document. Used by the simulator and by
    read-back verification of live writes. items: {item name: income account name} for invoices."""
    c = lambda v: int(round(float(v) * 100))
    ref = lambda d, k, default: (d.get(k) or {}).get("name") or default   # noqa: E731
    if entity == "Invoice":
        out = []
        for l in doc["Line"]:
            if l.get("DetailType") != "SalesItemLineDetail":
                continue
            item = l["SalesItemLineDetail"]["ItemRef"].get("name")
            out.append(((items or {}).get(item, item), -c(l["Amount"]), l.get("Description")))
        return out + [(ref(doc, "ARAccountRef", ar), -sum(x for _, x, _ in out), doc.get("PrivateNote"))]
    if entity == "CreditMemo":
        out = []
        for l in doc["Line"]:
            if l.get("DetailType") != "SalesItemLineDetail":
                continue
            item = l["SalesItemLineDetail"]["ItemRef"].get("name")
            out.append(((items or {}).get(item, item), c(l["Amount"]), l.get("Description")))
        return out + [(ref(doc, "ARAccountRef", ar), -sum(x for _, x, _ in out), doc.get("PrivateNote"))]
    if entity == "Payment":
        total = c(doc.get("TotalAmt", 0))
        if not total:
            return []
        return [(ref(doc, "DepositToAccountRef", "Undeposited Funds"), total, None), (ref(doc, "ARAccountRef", ar), -total, None)]
    if entity in ("Bill", "VendorCredit"):
        sign = 1 if entity == "Bill" else -1
        out = [(l["AccountBasedExpenseLineDetail"]["AccountRef"]["name"], sign * c(l["Amount"]), l.get("Description"))
               for l in doc["Line"] if l.get("DetailType") == "AccountBasedExpenseLineDetail"]
        return out + [(ref(doc, "APAccountRef", ap), -sign * sum(abs(x) for _, x, _ in out), doc.get("PrivateNote"))]
    if entity == "BillPayment":
        total = c(doc.get("TotalAmt", 0))
        if not total:                                      # applies a supplier credit to a bill: moves nothing (QuickBooks
            return []                                      # returns it without a bank account)
        src = (doc.get("CheckPayment") or {}).get("BankAccountRef") or (doc.get("CreditCardPayment") or {}).get("CCAccountRef")
        if not src:
            raise QBOError(f"bill payment of {total} has no bank or card account")
        return [(ref(doc, "APAccountRef", ap), total, None), (src["name"], -total, doc.get("PrivateNote"))]
    if entity == "Purchase":
        total = sum(c(l["Amount"]) for l in doc["Line"])
        sign = -1 if doc.get("Credit") else 1
        out = [(l["AccountBasedExpenseLineDetail"]["AccountRef"]["name"], sign * c(l["Amount"]), l.get("Description")) for l in doc["Line"]]
        return out + [(doc["AccountRef"]["name"], -sign * total, doc.get("PrivateNote"))]
    if entity == "Deposit":
        # a line linking a payment (or sales receipt) takes it out of Undeposited Funds; a negative line is a fee withheld
        total = sum(c(l["Amount"]) for l in doc["Line"])
        out = [((((l.get("DepositLineDetail") or {}).get("AccountRef") or {}).get("name")) or (UNDEPOSITED if l.get("LinkedTxn") else None),
                -c(l["Amount"]), l.get("Description")) for l in doc["Line"]]
        if any(a is None for a, _, _ in out):
            raise QBOError("a deposit line has no account and links no payment")
        return out + [(doc["DepositToAccountRef"]["name"], total, doc.get("PrivateNote"))]
    if entity == "SalesReceipt":
        out = []
        for l in doc["Line"]:
            if l.get("DetailType") != "SalesItemLineDetail":
                continue
            item = l["SalesItemLineDetail"]["ItemRef"].get("name")
            out.append(((items or {}).get(item, item), -c(l["Amount"]), l.get("Description")))
        return out + [(ref(doc, "DepositToAccountRef", UNDEPOSITED), -sum(x for _, x, _ in out), doc.get("PrivateNote"))]
    if entity == "Transfer":
        amt = c(doc["Amount"])
        return [(doc["ToAccountRef"]["name"], amt, doc.get("PrivateNote")), (doc["FromAccountRef"]["name"], -amt, doc.get("PrivateNote"))]
    if entity == "JournalEntry":
        out = []
        for l in doc["Line"]:
            d = l["JournalEntryLineDetail"]
            out.append((d["AccountRef"]["name"], c(l["Amount"]) * (1 if d["PostingType"] == "Debit" else -1), l.get("Description")))
        if sum(a for _, a, _ in out) != 0:
            raise QBOError("journal entry doesn't balance")
        return out
    raise QBOError(f"unsupported entity {entity}")


class SimulatedQBO:
    live = False
    label = "SIMULATED QuickBooks (local tables, nothing leaves this machine)"

    def __init__(self, conn, realm, fail_after=None):
        self.conn, self.realm = conn, realm
        self.fail_after = fail_after          # test hook: raise an uncertain error after N successful creates
        self.creates = 0

    def accounts(self):
        return {r["name"]: r["name"] for r in self.conn.execute("SELECT name FROM sim_qbo_accounts WHERE realm=?", (self.realm,))}

    def ensure_account(self, name, typ):
        if typ not in ACCOUNT_TYPES:
            raise QBOError(f"unknown account type {typ}")
        row = self.conn.execute("SELECT id FROM sim_qbo_accounts WHERE realm=? AND name=?", (self.realm, name)).fetchone()
        if row:
            return str(row["id"])
        nid = (self.conn.execute("SELECT IFNULL(MAX(id),0)+1 FROM sim_qbo_accounts WHERE realm=?", (self.realm,)).fetchone()[0])
        self.conn.execute("INSERT INTO sim_qbo_accounts (realm, id, name, type) VALUES (?,?,?,?)", (self.realm, nid, name, typ))
        return str(nid)

    def find_by_request(self, request_id):
        row = self.conn.execute("SELECT id FROM sim_qbo_txns WHERE realm=? AND request_id=?", (self.realm, request_id)).fetchone()
        return str(row["id"]) if row else None

    def ensure_name(self, kind, name, **data):
        """Customer, Vendor or Item (data: income_account for an item). Returns its id."""
        row = self.conn.execute("SELECT id FROM sim_qbo_names WHERE realm=? AND kind=? AND name=?", (self.realm, kind, name)).fetchone()
        if row:
            return str(row["id"])
        nid = self.conn.execute("SELECT IFNULL(MAX(id),0)+1 FROM sim_qbo_names WHERE realm=?", (self.realm,)).fetchone()[0]
        self.conn.execute("INSERT INTO sim_qbo_names (realm, kind, name, id, data_json) VALUES (?,?,?,?,?)",
                          (self.realm, kind, name, nid, json.dumps(data)))
        return str(nid)

    def items(self):
        return {r["name"]: json.loads(r["data_json"] or "{}").get("income_account")
                for r in self.conn.execute("SELECT name, data_json FROM sim_qbo_names WHERE realm=? AND kind='Item'", (self.realm,))}

    def delete(self, entity, qbo_id):
        row = self.conn.execute("SELECT entity FROM sim_qbo_txns WHERE realm=? AND id=?", (self.realm, int(qbo_id))).fetchone()
        if not row or row["entity"] != entity:
            raise QBOError(f"{entity} {qbo_id} not found")
        self._closed_guard(self.conn.execute("SELECT date FROM sim_qbo_txns WHERE realm=? AND id=?", (self.realm, int(qbo_id))).fetchone()["date"])
        self.conn.execute("DELETE FROM sim_qbo_lines WHERE realm=? AND txn_id=?", (self.realm, int(qbo_id)))
        self.conn.execute("DELETE FROM sim_qbo_txns WHERE realm=? AND id=?", (self.realm, int(qbo_id)))
        return {"Id": str(qbo_id), "status": "Deleted"}

    def _defaults(self):
        rows = self.conn.execute("SELECT name, type FROM sim_qbo_accounts WHERE realm=? ORDER BY id", (self.realm,)).fetchall()
        ar = next((r["name"] for r in rows if r["type"] == "Accounts Receivable"), "Accounts Receivable (A/R)")
        ap = next((r["name"] for r in rows if r["type"] == "Accounts Payable"), "Accounts Payable (A/P)")
        return ar, ap

    def system_account(self, typ):
        row = self.conn.execute("SELECT name FROM sim_qbo_accounts WHERE realm=? AND type=? ORDER BY id LIMIT 1", (self.realm, typ)).fetchone()
        return row["name"] if row else None

    def rename_account(self, old, new):
        self.conn.execute("UPDATE sim_qbo_accounts SET name=? WHERE realm=? AND name=?", (new, self.realm, old))
        self.conn.execute("UPDATE sim_qbo_lines SET account=? WHERE realm=? AND account=?", (new, self.realm, old))

    def retire_account(self, name):
        if self.balance(name, "9999-12-31"):
            raise QBOError(f"{name} has a balance; QuickBooks won't make it inactive")
        self.conn.execute("DELETE FROM sim_qbo_accounts WHERE realm=? AND name=?", (self.realm, name))

    def create(self, entity, doc, request_id):
        existing = self.find_by_request(request_id)
        if existing:                                   # same behaviour as QBO's requestid: return the original, no duplicate
            return existing
        self._closed_guard(doc.get("TxnDate"))
        accts = self.accounts()
        ar, ap = self._defaults()
        if entity in ("Invoice", "CreditMemo", "Bill", "VendorCredit"):
            # like QuickBooks: these always use the company's own A/R or A/P account, whatever the document says
            doc = {k: v for k, v in doc.items() if k not in ("ARAccountRef", "APAccountRef")}
        if entity == "Payment" and doc.get("DepositToAccountRef"):
            # like QuickBooks: a payment can only be deposited to a bank account; anything else lands in Undeposited Funds
            if self.account_types().get(doc["DepositToAccountRef"].get("name")) != "Bank":
                self.ensure_account("Undeposited Funds", "Other Current Asset")
                doc = dict(doc, DepositToAccountRef={"name": "Undeposited Funds"})
        if entity == "Deposit":
            waiting = {(u["entity"], u["id"]): u for u in self.undeposited("9999-12-31")}
            for ln in doc.get("Line") or []:
                for lk in ln.get("LinkedTxn") or []:
                    u = waiting.get((lk.get("TxnType"), str(lk.get("TxnId"))))
                    if u is None:
                        raise QBOError(f"{lk.get('TxnType')} {lk.get('TxnId')} isn't waiting in Undeposited Funds")
                    if _cents(ln.get("Amount") or 0) != u["amount"]:
                        raise QBOError(f"the deposit line for {lk.get('TxnType')} {lk.get('TxnId')} isn't its amount")
        lines = ledger_lines(entity, doc, self.items(), ar, ap)
        for name, _, _ in lines:
            if name not in accts:
                raise QBOError(f"account {name!r} doesn't exist in the company")
        nid = self.conn.execute("SELECT IFNULL(MAX(id),0)+1 FROM sim_qbo_txns WHERE realm=?", (self.realm,)).fetchone()[0]
        self.conn.execute("INSERT INTO sim_qbo_txns (realm, id, entity, request_id, date, doc_json) VALUES (?,?,?,?,?,?)",
                          (self.realm, nid, entity, request_id, doc["TxnDate"], json.dumps(doc)))
        for name, amt, memo in lines:
            self.conn.execute("INSERT INTO sim_qbo_lines (realm, txn_id, account, amount_cents, memo) VALUES (?,?,?,?,?)",
                              (self.realm, nid, name, amt, memo))
        self.creates += 1
        if self.fail_after is not None and self.creates > self.fail_after:
            raise QBOError("connection reset after send (outcome unknown)", uncertain=True)
        return str(nid)

    def read(self, entity, qbo_id):
        row = self.conn.execute("SELECT * FROM sim_qbo_txns WHERE realm=? AND id=?", (self.realm, int(qbo_id))).fetchone()
        if not row or row["entity"] != entity:
            raise QBOError(f"{entity} {qbo_id} not found")
        return json.loads(row["doc_json"])

    def balance(self, account, as_of):
        return self.conn.execute("SELECT IFNULL(SUM(l.amount_cents),0) FROM sim_qbo_lines l JOIN sim_qbo_txns t ON t.realm=l.realm AND t.id=l.txn_id "
                                 "WHERE l.realm=? AND l.account=? AND t.date<=?", (self.realm, account, as_of)).fetchone()[0]

    def activity(self, start, end):
        """{account: debit-positive sum} for the period."""
        rows = self.conn.execute("SELECT l.account, SUM(l.amount_cents) s FROM sim_qbo_lines l JOIN sim_qbo_txns t ON t.realm=l.realm AND t.id=l.txn_id "
                                 "WHERE l.realm=? AND t.date BETWEEN ? AND ? GROUP BY l.account", (self.realm, start, end))
        return {r["account"]: r["s"] for r in rows}

    def ledger(self, account, start, end):
        return [dict(r) for r in self.conn.execute(
            "SELECT t.id qbo_id, t.date, t.entity, l.amount_cents, l.memo FROM sim_qbo_lines l JOIN sim_qbo_txns t ON t.realm=l.realm AND t.id=l.txn_id "
            "WHERE l.realm=? AND l.account=? AND t.date BETWEEN ? AND ? ORDER BY t.date, t.id", (self.realm, account, start, end))]

    def account_types(self):
        return {r["name"]: r["type"] for r in self.conn.execute("SELECT name, type FROM sim_qbo_accounts WHERE realm=?", (self.realm,))}

    def set_account_type(self, name, typ):
        self.conn.execute("UPDATE sim_qbo_accounts SET type=? WHERE realm=? AND name=?", (typ, self.realm, name))

    def gl_lines(self, start, end, accounts=None):
        """Every ledger line in the period (or only those accounts'): {txn_id, entity, date, doc_number, memo, account, cents}."""
        out = []
        for r in self.conn.execute("SELECT t.id, t.entity, t.date, t.doc_json, l.account, l.amount_cents, l.memo FROM sim_qbo_lines l "
                                   "JOIN sim_qbo_txns t ON t.realm=l.realm AND t.id=l.txn_id WHERE l.realm=? AND t.date BETWEEN ? AND ? "
                                   "ORDER BY t.date, t.id", (self.realm, start, end)):
            doc = json.loads(r["doc_json"])
            if accounts is not None and r["account"] not in accounts:
                continue
            out.append({"txn_id": str(r["id"]), "entity": r["entity"], "date": r["date"], "doc_number": doc.get("DocNumber"),
                        "memo": doc.get("PrivateNote"), "account": r["account"], "cents": r["amount_cents"], "line_memo": r["memo"],
                        "payee": _payee(doc)})
        return out

    # ------------------------------------------------------------ what the ledger-native close reads and writes (docs/100)
    def chart(self):
        """[{id, name, type, subtype, classification}] with QuickBooks' own account types."""
        return [{"id": str(r["id"]), "name": r["name"], "type": r["type"], "subtype": None, "classification": CLASSIFICATION.get(r["type"])}
                for r in self.conn.execute("SELECT id, name, type FROM sim_qbo_accounts WHERE realm=? ORDER BY id", (self.realm,))]

    def trial_balance(self, as_of, fy_start):
        """{account: debit-positive cents} as QuickBooks' Trial Balance reports it: balance-sheet accounts cumulative to the
        date, income and expense for the fiscal year to date, earlier years' profit in Retained Earnings."""
        types = self.account_types()
        out, before = {}, 0
        for r in self.conn.execute("SELECT l.account, SUM(CASE WHEN t.date < ? THEN l.amount_cents ELSE 0 END) b, SUM(l.amount_cents) s "
                                   "FROM sim_qbo_lines l JOIN sim_qbo_txns t ON t.realm=l.realm AND t.id=l.txn_id WHERE l.realm=? AND t.date<=? "
                                   "GROUP BY l.account", (fy_start, self.realm, as_of)):
            if types.get(r["account"]) in PL_TYPES:
                out[r["account"]] = r["s"] - r["b"]
                before += r["b"]
            else:
                out[r["account"]] = out.get(r["account"], 0) + r["s"]
        if before:
            re_name = next((n for n, t in types.items() if t == "Equity" and "retained" in n.lower()), "Retained Earnings")
            out[re_name] = out.get(re_name, 0) + before
        return {a: v for a, v in out.items() if v}

    def update(self, entity, qbo_id, doc):
        """Replace a transaction (QuickBooks' full update: the document as it now stands, with its new lines)."""
        old = self.read(entity, qbo_id)
        if doc.get("SyncToken") is not None and str(doc["SyncToken"]) != str(old.get("SyncToken") or 0):
            raise QBOError("Stale Object Error: the transaction was changed since it was read (5010)", status=400)
        self._closed_guard(old.get("TxnDate"), doc.get("TxnDate"))
        ar, ap = self._defaults()
        lines = ledger_lines(entity, doc, self.items(), ar, ap)
        accts = self.accounts()
        for name, _, _ in lines:
            if name not in accts:
                raise QBOError(f"account {name!r} doesn't exist in the company")
        doc = dict({k: v for k, v in doc.items() if k != "SyncToken"}, Id=str(qbo_id), SyncToken=str(int(old.get("SyncToken") or 0) + 1))
        self.conn.execute("UPDATE sim_qbo_txns SET date=?, doc_json=? WHERE realm=? AND id=?", (doc["TxnDate"], json.dumps(doc), self.realm, int(qbo_id)))
        self.conn.execute("DELETE FROM sim_qbo_lines WHERE realm=? AND txn_id=?", (self.realm, int(qbo_id)))
        for name, amt, memo in lines:
            self.conn.execute("INSERT INTO sim_qbo_lines (realm, txn_id, account, amount_cents, memo) VALUES (?,?,?,?,?)",
                              (self.realm, int(qbo_id), name, amt, memo))
        return str(qbo_id)

    def open_items(self, kind, as_of):
        """Invoices ('Invoice') or bills ('Bill') with a balance still due at the date: [{id, number, name, date, due, total, open}]."""
        pay_entity, credit_entity = ("Payment", "CreditMemo") if kind == "Invoice" else ("BillPayment", "VendorCredit")
        paid = {}
        for r in self.conn.execute("SELECT doc_json FROM sim_qbo_txns WHERE realm=? AND entity IN (?,?) AND date<=?",
                                   (self.realm, pay_entity, credit_entity, as_of)):
            d = json.loads(r["doc_json"])
            for ln in d.get("Line") or []:
                for lk in ln.get("LinkedTxn") or []:
                    if lk.get("TxnType") == kind:
                        paid[str(lk["TxnId"])] = paid.get(str(lk["TxnId"]), 0) + _cents(ln.get("Amount") or 0)
        out = []
        for r in self.conn.execute("SELECT id, date, doc_json FROM sim_qbo_txns WHERE realm=? AND entity=? AND date<=? ORDER BY date, id",
                                   (self.realm, kind, as_of)):
            d = json.loads(r["doc_json"])
            total = sum(_cents(ln["Amount"]) for ln in d.get("Line") or [] if ln.get("DetailType") in ("SalesItemLineDetail", "AccountBasedExpenseLineDetail"))
            left = total - paid.get(str(r["id"]), 0)
            if left:
                out.append({"id": str(r["id"]), "number": d.get("DocNumber"), "name": _payee(d), "date": r["date"], "due": d.get("DueDate"),
                            "total": total, "open": left})
        return out

    def undeposited(self, as_of):
        """Payments and sales receipts received into Undeposited Funds that no deposit has taken yet:
        [{entity, id, date, amount, name, number}]."""
        linked = set()
        for r in self.conn.execute("SELECT doc_json FROM sim_qbo_txns WHERE realm=? AND entity='Deposit'", (self.realm,)):
            for ln in json.loads(r["doc_json"]).get("Line") or []:
                for lk in ln.get("LinkedTxn") or []:
                    linked.add((lk.get("TxnType"), str(lk.get("TxnId"))))
        out = []
        for r in self.conn.execute("SELECT id, entity, date, doc_json FROM sim_qbo_txns WHERE realm=? AND entity IN ('Payment','SalesReceipt') "
                                   "AND date<=? ORDER BY date, id", (self.realm, as_of)):
            d = json.loads(r["doc_json"])
            if ((d.get("DepositToAccountRef") or {}).get("name") or UNDEPOSITED) != UNDEPOSITED or (r["entity"], str(r["id"])) in linked:
                continue
            amt = _cents(d.get("TotalAmt") or 0) or sum(_cents(ln.get("Amount") or 0) for ln in d.get("Line") or []
                                                         if ln.get("DetailType") in (None, "SalesItemLineDetail"))
            out.append({"entity": r["entity"], "id": str(r["id"]), "date": r["date"], "amount": amt, "name": _payee(d), "number": d.get("DocNumber")})
        return out

    def close_date(self):
        row = self.conn.execute("SELECT value FROM sim_qbo_prefs WHERE realm=? AND key='BookCloseDate'", (self.realm,)).fetchone()
        return row["value"] if row else None

    def set_close_date(self, day):
        self.conn.execute("INSERT INTO sim_qbo_prefs (realm, key, value) VALUES (?, 'BookCloseDate', ?) "
                          "ON CONFLICT (realm, key) DO UPDATE SET value=excluded.value", (self.realm, day))
        return self.close_date()

    def _closed_guard(self, *dates):
        """Like QuickBooks with a closing date (and no closing-date password given): nothing on or before it changes."""
        closed = self.close_date()
        if closed and any(d and d <= closed for d in dates):
            raise QBOError(f"the books are closed through {closed}: a transaction dated then can't be changed")


PL_TYPES = {"Income", "Other Income", "Cost of Goods Sold", "Expense", "Other Expense"}
CLASSIFICATION = {"Bank": "Asset", "Accounts Receivable": "Asset", "Other Current Asset": "Asset", "Fixed Asset": "Asset", "Other Asset": "Asset",
                  "Accounts Payable": "Liability", "Credit Card": "Liability", "Other Current Liability": "Liability",
                  "Long Term Liability": "Liability", "Equity": "Equity", "Income": "Revenue", "Other Income": "Revenue",
                  "Cost of Goods Sold": "Expense", "Expense": "Expense", "Other Expense": "Expense"}


def _payee(doc):
    for k in ("CustomerRef", "VendorRef", "EntityRef"):
        v = doc.get(k)
        if isinstance(v, dict) and v.get("name"):
            return v["name"]
    return None


QBO_TO_OURS = {"Bank": "Bank", "Credit Card": "Credit Card", "Long Term Liability": "Long Term Liability",
               "Other Current Liability": "Other Current Liability", "Accounts Payable": "Accounts Payable",
               "Other Current Asset": "Other Current Asset", "Accounts Receivable": "Accounts Receivable",
               "Fixed Asset": "Fixed Asset", "Other Asset": "Fixed Asset", "Equity": "Equity", "Income": "Income",
               "Other Income": "Other Income", "Cost of Goods Sold": "Cost of Goods Sold", "Expense": "Expense",
               "Other Expense": "Expense"}
GL_ENTITY = {"Expense": "Purchase", "Check": "Purchase", "Credit Card Expense": "Purchase", "Credit Card Credit": "Purchase",
             "Cash Expense": "Purchase", "Deposit": "Deposit", "Transfer": "Transfer", "Journal Entry": "JournalEntry",
             "Invoice": "Invoice", "Payment": "Payment", "Bill": "Bill", "Bill Payment (Check)": "BillPayment",
             "Bill Payment (Credit Card)": "BillPayment", "Vendor Credit": "VendorCredit", "Sales Receipt": "SalesReceipt",
             "Credit Memo": "CreditMemo", "Refund": "RefundReceipt"}


def _cents(v):
    return int(round(float(str(v).replace(",", "") or 0) * 100))


def _data_rows(rows):
    """Every Data row in a QBO report, however deeply its sections are nested."""
    for r in (rows or {}).get("Row", []):
        if "ColData" in r and r.get("type", "Data") == "Data":
            yield r["ColData"]
        if "Rows" in r:
            yield from _data_rows(r["Rows"])


def _keychain_put(name, value):
    import os
    import subprocess
    if os.environ.get("ACQ_NO_KEYCHAIN"):
        return                                             # tests and servers never write the owner's keychain
    subprocess.run(["security", "add-generic-password", "-U", "-s", "nhb-acq", "-a", name, "-w", value], capture_output=True)


def _keychain_delete(name):
    import os
    import subprocess
    if os.environ.get("ACQ_NO_KEYCHAIN"):
        return
    subprocess.run(["security", "delete-generic-password", "-s", "nhb-acq", "-a", name], capture_output=True)


class LiveQBO:
    """Intuit Accounting API v3 over HTTPS. Credentials come from the macOS keychain (service nhb-acq): the app's keys
    (intuit_dev_client_id/secret for sandbox companies, intuit_client_id/secret for real ones) and the company's
    intuit_refresh_token:<realm>, written by `python3 -m ops intuit-connect`. Never logs tokens.

    Reads come from QuickBooks' own reports, so the books are always the source of truth:
      balance()  BalanceSheet as of a date (balance-sheet accounts); for income/expense accounts, the fiscal year to date
      activity() ProfitAndLoss for the period (income/expense) and BalanceSheet(end) - BalanceSheet(day before start)
      ledger()   GeneralLedger for one account, checked against activity() so a misread sign can never pass silently
    Assumes a January fiscal year start (checked by `ops intuit-test`)."""
    live = True
    MINOR = "75"
    MIN_INTERVAL = 0.13            # about 460 calls a minute, under Intuit's 500 per minute per company

    def __init__(self, realm, secrets=None, transport=None, sleep=time.sleep, sandbox=False, basis="cash", store=None):
        from acq import secrets_store
        self.realm, self.sleep, self.sandbox = realm, sleep, sandbox
        self.secrets = secrets or secrets_store
        self.transport = transport or self._http
        self.store = store or _keychain_put
        self.method = "Cash" if basis == "cash" else "Accrual"
        self.BASE = ("https://sandbox-quickbooks.api.intuit.com" if sandbox else "https://quickbooks.api.intuit.com") + "/v3/company"
        self.label = f"LIVE QuickBooks Online{' SANDBOX' if sandbox else ''} (Intuit Accounting API, company {realm})"
        self.key_prefix = "intuit_dev" if sandbox else "intuit"
        self._token, self._exp, self._last = None, 0, 0.0
        self.last_tid = None
        import threading
        import uuid
        self._pace, self._authlock = threading.Lock(), threading.Lock()    # safe for parallel workers
        # list objects (accounts, customers, vendors, items) are found by name first; their create request ids carry a
        # per-session nonce so a retry in this session is safe but a later session never gets a deleted object back
        self._nonce = uuid.uuid4().hex[:6]
        self._accounts = self._meta = None
        self._reports = {}

    def _http(self, method, url, headers, body):
        req = urllib.request.Request(url, method=method, data=body, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                self.last_tid = r.headers.get("intuit_tid")
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            self.last_tid = e.headers.get("intuit_tid") if e.headers else None    # Intuit's id for its support to trace the call
            return e.code, e.read()

    def _auth(self):
        if self._token and time.time() < self._exp - 60:
            return self._token
        with self._authlock:
            if self._token and time.time() < self._exp - 60:
                return self._token
            return self._refresh()

    def _refresh(self):
        cid, sec = self.secrets.get(f"{self.key_prefix}_client_id"), self.secrets.get(f"{self.key_prefix}_client_secret")
        rt = self.secrets.get(f"intuit_refresh_token:{self.realm}")
        if not (cid and sec and rt):
            raise QBOError(f"QuickBooks isn't connected: {self.key_prefix}_client_id/secret and the company's refresh token must be in "
                           "the keychain (run: python3 -m ops intuit-connect)")
        import base64
        status, body = self.transport("POST", "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer",
                                      {"Authorization": "Basic " + base64.b64encode(f"{cid}:{sec}".encode()).decode(),
                                       "Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
                                      urllib.parse.urlencode({"grant_type": "refresh_token", "refresh_token": rt}).encode())
        if status != 200:
            why = "the sign-in to this company expired or was disconnected" if b"invalid_grant" in (body or b"") else "the token service refused it"
            raise QBOError(f"token refresh failed ({status}: {why}); reconnect the company from its QuickBooks tab "
                           "(the sign-in to this company must be renewed)", status=status)
        tok = json.loads(body)
        self._token, self._exp = tok["access_token"], time.time() + int(tok.get("expires_in", 3600))
        if tok.get("refresh_token") and tok["refresh_token"] != rt:
            self.store(f"intuit_refresh_token:{self.realm}", tok["refresh_token"])   # Intuit rotates refresh tokens
        return self._token

    NET_RETRIES = 11

    def _call(self, method, path, body=None, params=None, attempts=5):
        params = dict(params or {}, minorversion=self.MINOR)
        url = f"{self.BASE}/{self.realm}/{path}?{urllib.parse.urlencode(params)}"
        net_fails, i = 0, 0
        while i < attempts:
            with self._pace:                               # one request start every MIN_INTERVAL across all workers
                wait = self.MIN_INTERVAL - (time.monotonic() - self._last)
                if wait > 0:
                    self.sleep(wait)
                self._last = time.monotonic()
            headers = {"Authorization": f"Bearer {self._auth()}", "Accept": "application/json", "Content-Type": "application/json"}
            try:
                status, raw = self.transport(method, url, headers, json.dumps(body).encode() if body is not None else None)
            except OSError as e:
                # a dropped connection: reads are safe to repeat; a create is too, because QuickBooks answers a repeated
                # requestid with the original. A delete or update without one is uncertain and isn't repeated.
                # Outages (DNS, TLS timeouts) can last minutes: up to NET_RETRIES tries over about six minutes.
                safe = method == "GET" or "requestid" in params or params.get("operation") == "delete"
                net_fails += 1
                if safe and net_fails < self.NET_RETRIES:
                    self.sleep(min(60, 2 ** net_fails))
                    continue
                raise QBOError(f"network error: {e}", uncertain=method == "POST") from None
            i += 1
            if status in (425, 429) or status >= 500:      # 425 "too early": Intuit's edge didn't process it (seen 2026-09-29)
                self.sleep(min(60, 2 ** (i + 1)))       # same requestid on retry: QBO returns the original, never a duplicate
                continue
            if status == 401 and i == 1:
                self._token = None
                continue
            if status >= 400:
                tid = getattr(self, "last_tid", None)
                raise QBOError(f"QuickBooks error {status}: {raw[:300]!r}" + (f" (intuit_tid {tid})" if tid else ""), status=status)
            return json.loads(raw)
        raise QBOError("QuickBooks kept throttling or failing; stopped after bounded retries", uncertain=method == "POST")

    def company_info(self):
        return self._call("GET", f"companyinfo/{self.realm}")["CompanyInfo"]

    def _load_accounts(self):
        out = self._call("GET", "query", params={"query": "select Id, Name, FullyQualifiedName, AccountType, AccountSubType, Classification "
                                                             "from Account maxresults 1000"})
        rows = out.get("QueryResponse", {}).get("Account", [])
        self._accounts = {a.get("FullyQualifiedName", a["Name"]): a["Id"] for a in rows}
        # QuickBooks moves earlier years' profit into Retained Earnings with no transaction: its ledger lines never add up to
        # its change across a year end (found by the Intuit-shaped double, docs/102 step 1)
        self._retained = {a.get("FullyQualifiedName", a["Name"]) for a in rows if a.get("AccountSubType") == "RetainedEarnings"
                          or (a.get("AccountType") == "Equity" and "retained earnings" in a["Name"].lower())}
        self._meta = {a["Id"]: (a.get("FullyQualifiedName", a["Name"]), QBO_TO_OURS.get(a["AccountType"], "Expense"), a.get("Classification")) for a in rows}

    def accounts(self):
        if self._accounts is None:
            self._load_accounts()
        return self._accounts

    def account_types(self):
        self.accounts()
        return {name: typ for name, typ, _ in self._meta.values()}

    def ensure_account(self, name, typ):
        accts = self.accounts()
        if name in accts:
            return accts[name]
        body = {"Name": name, "AccountType": ACCOUNT_TYPES[typ][0]}
        sub = SUBTYPE_BY_NAME.get(name) or SUBTYPES.get(typ)
        if sub:
            body["AccountSubType"] = sub
        import hashlib
        out = self._call("POST", "account", body, params={"requestid": f"acct-{self._nonce}-{hashlib.sha1(name.encode()).hexdigest()[:16]}"})
        a = out["Account"]
        accts[name] = a["Id"]
        self._meta[a["Id"]] = (name, typ, a.get("Classification"))
        return accts[name]

    def system_account(self, typ):
        """The account QuickBooks itself uses for invoices (Accounts Receivable) or bills (Accounts Payable): the first
        one of that type the company has."""
        self.accounts()
        rows = sorted(((int(aid), meta[0]) for aid, meta in self._meta.items() if meta[1] == typ), key=lambda x: x[0])
        return rows[0][1] if rows else None

    def rename_account(self, old, new):
        aid = self.accounts()[old]
        cur = self._call("GET", f"account/{aid}")["Account"]
        self._call("POST", "account", {"Id": aid, "SyncToken": cur["SyncToken"], "sparse": True, "Name": new})
        self._accounts[new] = self._accounts.pop(old)
        self._meta[aid] = (new,) + tuple(self._meta[aid][1:])

    def retire_account(self, name):
        """Make an account inactive (QuickBooks refuses while it has a balance, which is the safeguard we want)."""
        aid = self.accounts()[name]
        cur = self._call("GET", f"account/{aid}")["Account"]
        self._call("POST", "account", {"Id": aid, "SyncToken": cur["SyncToken"], "sparse": True, "Name": cur["Name"], "Active": False})
        self._accounts.pop(name)
        self._meta.pop(aid, None)

    def set_account_type(self, name, typ):
        aid = self.accounts()[name]
        cur = self._call("GET", f"account/{aid}")["Account"]
        body = {"Id": aid, "SyncToken": cur["SyncToken"], "sparse": True, "Name": cur["Name"], "AccountType": ACCOUNT_TYPES[typ][0]}
        sub = SUBTYPES.get(typ)
        if sub:
            body["AccountSubType"] = sub
        self._call("POST", "account", body)
        self._meta[aid] = (name, typ, self._meta[aid][2])

    def _with_ids(self, doc):
        accts = self.accounts()
        s = json.dumps(doc)
        for name, aid in accts.items():
            s = s.replace(json.dumps({"name": name}), json.dumps({"name": name, "value": aid}))
        return json.loads(s)

    def create(self, entity, doc, request_id):
        self._reports.clear()
        out = self._call("POST", entity.lower(), self._with_ids(doc), params={"requestid": request_id})
        return out[entity]["Id"]

    def find_by_request(self, request_id):
        return None      # QBO has no lookup by requestid; re-sending the same create with the same requestid is the recovery

    def ensure_name(self, kind, name, **data):
        """Find or create a Customer, Vendor or Item by name (an Item needs data income_account = an account name)."""
        cache = self.__dict__.setdefault("_names", {})
        if (kind, name) in cache:
            return cache[(kind, name)]
        field = "Name" if kind == "Item" else "DisplayName"
        q = name.replace("'", "\\'")
        rows = self._call("GET", "query", params={"query": f"select Id from {kind} where {field} = '{q}'"}).get("QueryResponse", {}).get(kind, [])
        if rows:
            cache[(kind, name)] = rows[0]["Id"]
            return rows[0]["Id"]
        body = {field: name}
        if kind == "Item":
            body.update(Type="Service", IncomeAccountRef={"value": self.accounts()[data["income_account"]]})
        import hashlib                                   # Intuit counts the URL-encoded id (a space is 3 characters): hash the name
        out = self._call("POST", kind.lower(), body, params={"requestid": f"{kind}-{self._nonce}-{hashlib.sha1(name.encode()).hexdigest()[:16]}"})
        cache[(kind, name)] = out[kind]["Id"]
        if kind == "Item":
            self.__dict__.setdefault("_items", {})[name] = data["income_account"]
        return cache[(kind, name)]

    def items(self):
        if "_items_loaded" not in self.__dict__:
            rows = self._call("GET", "query", params={"query": "select Id, Name, IncomeAccountRef from Item maxresults 1000"}
                              ).get("QueryResponse", {}).get("Item", [])
            meta = self._meta or {}
            self.accounts()
            for r in rows:
                acct = (r.get("IncomeAccountRef") or {}).get("value")
                if acct in self._meta:
                    self.__dict__.setdefault("_items", {})[r["Name"]] = self._meta[acct][0]
            self._items_loaded = True
            _ = meta
        return dict(self.__dict__.get("_items", {}))

    def delete(self, entity, qbo_id):
        """Returns QuickBooks' answer ({Id, status: Deleted}), which is the proof the caller checks."""
        self._reports.clear()
        cur = self.read(entity, qbo_id)
        out = self._call("POST", entity.lower(), {"Id": cur["Id"], "SyncToken": cur["SyncToken"]}, params={"operation": "delete"})
        return out.get(entity) if isinstance(out, dict) else None

    def read(self, entity, qbo_id):
        return self._call("GET", f"{entity.lower()}/{qbo_id}")[entity]

    def changes(self, since):
        """CDC change detector for ledger-first reads. Any incomplete result forces a complete GL refresh."""
        from .books.ledger_changes import ENTITIES, parse_cdc
        return parse_cdc(self._call("GET", "cdc", params={"entities": ",".join(ENTITIES), "changedSince": since}))

    def report(self, name, **params):
        key = (name, tuple(sorted(params.items())))
        if key not in self._reports:
            self._reports[key] = self._call("GET", f"reports/{name}", params=dict(params, accounting_method=self.method))
        return self._reports[key]

    def _amounts(self, rep):
        """{account name: debit-positive cents} from a BalanceSheet or ProfitAndLoss report (Total column)."""
        self.accounts()
        out = {}
        money_cols = [i for i, c in enumerate(rep.get("Columns", {}).get("Column", [])) if c.get("ColType") == "Money"]
        if not money_cols:
            return out                                     # QuickBooks omits the amount column when nothing has a balance
        i_amt = money_cols[-1]
        for cols in _data_rows(rep.get("Rows")):
            aid = cols[0].get("id")
            if not aid or aid not in self._meta or len(cols) <= i_amt:
                continue                                   # e.g. the Net Income line, which isn't an account
            name, typ, cls = self._meta[aid]
            v = _cents(cols[i_amt].get("value"))
            out[name] = out.get(name, 0) + (v if cls in ("Asset", "Expense") else -v)
        return out

    def _bs(self, as_of):
        return self._amounts(self.report("BalanceSheet", start_date=as_of, end_date=as_of, summarize_column_by="Total"))

    def _pl(self, start, end):
        return self._amounts(self.report("ProfitAndLoss", start_date=start, end_date=end, summarize_column_by="Total"))

    def balance(self, account, as_of):
        typ = self.account_types().get(account)
        if typ in ("Income", "Other Income", "Cost of Goods Sold", "Expense"):
            return self._pl(as_of[:4] + "-01-01", as_of).get(account, 0)
        return self._bs(as_of).get(account, 0)

    def activity(self, start, end):
        from datetime import date, timedelta
        before = (date.fromisoformat(start) - timedelta(days=1)).isoformat()
        types = self.account_types()
        end_bs, start_bs = self._bs(end), self._bs(before)
        out = {a: end_bs.get(a, 0) - start_bs.get(a, 0) for a in set(end_bs) | set(start_bs)
               if types.get(a) not in ("Income", "Other Income", "Cost of Goods Sold", "Expense")}
        out.update(self._pl(start, end))
        return {a: v for a, v in out.items() if v}

    def ledger(self, account, start, end):
        aid = self.accounts().get(account)
        if aid is None:
            return []
        rep = self.report("GeneralLedger", start_date=start, end_date=end, account=aid)
        cols = rep.get("Columns", {}).get("Column", [])
        keys = [next((m["Value"] for m in c.get("MetaData", []) if m.get("Name") == "ColKey"), c.get("ColTitle", "")) for c in cols]
        at = lambda *names: next((i for i, k in enumerate(keys) if k in names), None)
        i_date, i_type, i_memo = at("tx_date", "Date"), at("txn_type", "Transaction Type"), at("memo", "Memo/Description")
        i_amt = at("subt_nat_amount", "Amount")
        if None in (i_date, i_type, i_amt):
            raise QBOError(f"GeneralLedger report for {account} is missing expected columns: {keys}")
        cls = self._meta[aid][2]
        sign = 1 if cls in ("Asset", "Expense") else -1
        out = []
        for c in _data_rows(rep.get("Rows")):
            if not c[i_type].get("id"):
                continue                                   # beginning balance and total lines
            out.append({"qbo_id": c[i_type]["id"], "date": c[i_date]["value"], "entity": GL_ENTITY.get(c[i_type]["value"], c[i_type]["value"]),
                        "amount_cents": sign * _cents(c[i_amt].get("value")), "memo": c[i_memo]["value"] if i_memo is not None else None})
        got, want = sum(x["amount_cents"] for x in out), self.activity(start, end).get(account, 0)
        if got != want and account not in getattr(self, "_retained", set()):
            raise QBOError(f"GeneralLedger for {account} sums to {got} but the period activity is {want}; not using it")
        return out

    SLICE_DAYS = 92                                       # a long period is read a quarter at a time (Intuit's report size limits)

    def gl_lines(self, start, end, accounts=None):
        """Every ledger line in the period (or only those accounts'), read from the GeneralLedger report one account at a
        time (with the document number), each account's lines checked against its period activity. {txn_id, entity, date,
        doc_number, memo, account, cents} with cents debit-positive. A period longer than a quarter is read in slices."""
        from datetime import date, timedelta
        a, b = date.fromisoformat(start), date.fromisoformat(end)
        if (b - a).days > self.SLICE_DAYS:
            out, cur = [], a
            while cur <= b:
                stop = min(b, cur + timedelta(days=self.SLICE_DAYS - 1))
                out += self._gl_slice(cur.isoformat(), stop.isoformat(), accounts)
                cur = stop + timedelta(days=1)
            return out
        return self._gl_slice(start, end, accounts)

    def _gl_slice(self, start, end, accounts=None):
        out = []
        activity = self.activity(start, end)
        for name, aid in sorted(self.accounts().items()):
            if accounts is not None and name not in accounts:
                continue
            rep = self.report("GeneralLedger", start_date=start, end_date=end, account=aid,
                              columns="tx_date,txn_type,doc_num,name,memo,subt_nat_amount")
            cols = rep.get("Columns", {}).get("Column", [])
            keys = [next((m["Value"] for m in c.get("MetaData", []) if m.get("Name") == "ColKey"), c.get("ColTitle", "")) for c in cols]
            at = lambda *names: next((i for i, k in enumerate(keys) if k in names), None)   # noqa: E731
            i_date, i_type, i_doc = at("tx_date", "Date"), at("txn_type", "Transaction Type"), at("doc_num", "Num")
            i_memo, i_amt, i_name = at("memo", "Memo/Description"), at("subt_nat_amount", "Amount"), at("name", "Name")
            if None in (i_date, i_type, i_amt):
                continue                                   # no activity: QuickBooks leaves the columns out
            sign = 1 if self._meta[aid][2] in ("Asset", "Expense") else -1
            mine = []
            for c in _data_rows(rep.get("Rows")):
                if len(c) <= max(i_date, i_type, i_amt) or not c[i_type].get("id"):
                    continue
                mine.append({"txn_id": c[i_type]["id"], "entity": GL_ENTITY.get(c[i_type]["value"], c[i_type]["value"]),
                             "date": c[i_date]["value"], "doc_number": c[i_doc]["value"] if i_doc is not None else None,
                             "memo": c[i_memo]["value"] if i_memo is not None else None, "account": name,
                             "cents": sign * _cents(c[i_amt].get("value")),
                             "payee": (c[i_name].get("value") or None) if i_name is not None and len(c) > i_name else None})
            if sum(x["cents"] for x in mine) != activity.get(name, 0) and name not in getattr(self, "_retained", set()):
                raise QBOError(f"GeneralLedger for {name} sums to {sum(x['cents'] for x in mine)} but the period activity is "
                               f"{activity.get(name, 0)}; not using it")
            out += mine
        return out

    # ------------------------------------------------------------ what the ledger-native close reads and writes (docs/100)
    def chart(self):
        """[{id, name, type, subtype, classification, active}] with QuickBooks' own account types."""
        out, start = [], 1
        while True:
            rows = self._call("GET", "query", params={"query": "select Id, Name, FullyQualifiedName, AccountType, AccountSubType, Classification, "
                                                               f"Active from Account STARTPOSITION {start} MAXRESULTS 1000"}
                              ).get("QueryResponse", {}).get("Account", [])
            out += [{"id": a["Id"], "name": a.get("FullyQualifiedName", a["Name"]), "type": a["AccountType"], "subtype": a.get("AccountSubType"),
                     "classification": a.get("Classification"), "active": a.get("Active", True)} for a in rows]
            if len(rows) < 1000:
                return out
            start += 1000

    def trial_balance(self, as_of, fy_start):
        """QuickBooks' own Trial Balance report on the client's basis: {account: debit-positive cents}. Intuit ignores an
        end date alone, so the fiscal year's first day goes with it (seen on the sandbox, 2026-10-12)."""
        self.accounts()
        rep = self.report("TrialBalance", start_date=fy_start, end_date=as_of)
        end = (rep.get("Header") or {}).get("EndPeriod")
        if end not in (None, as_of):
            raise QBOError(f"QuickBooks reported the trial balance to {end}, not {as_of}: not used")
        out = {}
        for cols in _data_rows(rep.get("Rows")):
            aid = cols[0].get("id")
            if not aid or len(cols) < 3:
                continue
            name = self._meta[aid][0] if aid in (self._meta or {}) else cols[0].get("value")
            out[name] = out.get(name, 0) + _cents(cols[1].get("value") or 0) - _cents(cols[2].get("value") or 0)
        return {a: v for a, v in out.items() if v}

    def update(self, entity, qbo_id, doc):
        """A full update: the document as it now stands (QuickBooks needs its current SyncToken; a stale one is refused,
        which is how a change someone made meanwhile is never overwritten)."""
        self._reports.clear()
        token = doc.get("SyncToken")                      # the version the change was prepared from (docs/104 A01) ...
        if token is None:
            token = self.read(entity, qbo_id)["SyncToken"]   # ... or, for a document built from scratch, the current one
        body = self._with_ids(dict(doc, Id=str(qbo_id), SyncToken=str(token)))
        return self._call("POST", entity.lower(), body)[entity]["Id"]

    AGING = {"Invoice": "AgedReceivableDetail", "Bill": "AgedPayableDetail"}

    def open_items(self, kind, as_of):
        """Invoices or bills with a balance due at the date. QuickBooks' Balance field is today's, so an earlier month-end
        (a cleanup month, a month closed late) is read from the aging detail report at that date (docs/104 A04).
        [{id, number, name, date, due, total, open}]"""
        from datetime import date as _date
        if as_of < _date.today().isoformat():
            try:
                return self._aged(kind, as_of)
            except QBOError:
                pass                                       # the report isn't available for this company: today's balances, said so
        out, start = [], 1
        while True:
            rows = self._call("GET", "query", params={"query": f"select * from {kind} where Balance > '0' STARTPOSITION {start} MAXRESULTS 1000"}
                              ).get("QueryResponse", {}).get(kind, [])
            out += [{"id": r["Id"], "number": r.get("DocNumber"), "name": _payee(r), "date": r.get("TxnDate"), "due": r.get("DueDate"),
                     "total": _cents(r.get("TotalAmt") or 0), "open": _cents(r.get("Balance") or 0)} for r in rows if (r.get("TxnDate") or "") <= as_of]
            if len(rows) < 1000:
                return out
            start += 1000

    def _query(self, entity, where):
        out, start = [], 1
        while True:
            rows = self._call("GET", "query", params={"query": f"select * from {entity} where {where} STARTPOSITION {start} MAXRESULTS 1000"}
                              ).get("QueryResponse", {}).get(entity, [])
            out += rows
            if len(rows) < 1000:
                return out
            start += 1000

    def undeposited(self, as_of, days=180):
        """Payments and sales receipts received into Undeposited Funds (from the last half year) that no deposit links yet:
        [{entity, id, date, amount, name, number}]. QuickBooks keeps the link on the deposit's line (LinkedTxn)."""
        from datetime import date, timedelta
        start = (date.fromisoformat(as_of) - timedelta(days=days)).isoformat()
        self.accounts()
        linked = {(lk.get("TxnType"), str(lk.get("TxnId"))) for d in self._query("Deposit", f"TxnDate >= '{start}'")
                  for ln in d.get("Line") or [] for lk in ln.get("LinkedTxn") or []}
        out = []
        for ent in ("Payment", "SalesReceipt"):
            for r in self._query(ent, f"TxnDate >= '{start}' AND TxnDate <= '{as_of}'"):
                to = r.get("DepositToAccountRef") or {}
                name = (self._meta.get(str(to.get("value"))) or (to.get("name"),))[0] if to else UNDEPOSITED
                if (name or UNDEPOSITED) != UNDEPOSITED or (ent, str(r["Id"])) in linked or not _cents(r.get("TotalAmt") or 0):
                    continue
                out.append({"entity": ent, "id": str(r["Id"]), "date": r.get("TxnDate"), "amount": _cents(r.get("TotalAmt") or 0),
                            "name": _payee(r), "number": r.get("DocNumber") or r.get("PaymentRefNum")})
        return sorted(out, key=lambda u: (u["date"], u["id"]))

    def _aged(self, kind, as_of):
        rep = self.report(self.AGING[kind], report_date=as_of, aging_method="Report_Date", columns="tx_date,txn_type,doc_num,name,due_date,subt_amount,subt_open_bal")
        cols = rep.get("Columns", {}).get("Column", [])
        keys = [next((m["Value"] for m in c.get("MetaData", []) if m.get("Name") == "ColKey"), c.get("ColTitle", "")) for c in cols]
        at = lambda *names: next((i for i, k in enumerate(keys) if k in names), None)   # noqa: E731
        i_date, i_type, i_doc = at("tx_date", "Date"), at("txn_type", "Transaction Type"), at("doc_num", "Num")
        i_name, i_due = at("name", "cust_name", "vend_name", "Customer", "Vendor", "Name"), at("due_date", "Due Date")
        i_amt, i_open = at("subt_amount", "Amount"), at("subt_open_bal", "Open Balance")
        if None in (i_type, i_open):
            raise QBOError(f"{self.AGING[kind]} without the columns needed")
        out = []
        for c in _data_rows(rep.get("Rows")):
            if len(c) <= max(i_type, i_open) or not c[i_type].get("id"):
                continue
            open_ = _cents(c[i_open].get("value") or 0)
            if not open_:
                continue
            out.append({"id": c[i_type]["id"], "number": (c[i_doc].get("value") or None) if i_doc is not None else None,
                        "name": (c[i_name].get("value") or None) if i_name is not None else None,
                        "date": c[i_date].get("value") if i_date is not None else None, "due": c[i_due].get("value") if i_due is not None else None,
                        "total": _cents(c[i_amt].get("value") or 0) if i_amt is not None else open_, "open": open_})
        return out

    def close_date(self):
        prefs = self._call("GET", "preferences")["Preferences"]
        return (prefs.get("AccountingInfoPrefs") or {}).get("BookCloseDate")

    def set_close_date(self, day):
        """Preferences.AccountingInfoPrefs.BookCloseDate, by a sparse update. Not yet run against an Intuit sandbox."""
        prefs = self._call("GET", "preferences")["Preferences"]
        self._call("POST", "preferences", {"sparse": True, "SyncToken": prefs["SyncToken"], "AccountingInfoPrefs": {"BookCloseDate": day}})
        return self.close_date()
