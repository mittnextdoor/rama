"""Fixing the ledger itself (docs/100 §3, step 3): each fix is one small QuickBooks transaction, sent once and read back.

  create        Deposit (money in), Purchase (money out, or a card charge), Purchase with Credit (a card refund)
  transfer      Transfer between two of the client's accounts
  receive       Payment applied to the open invoice
  pay_bill      BillPayment applied to the open bill
  recategorize  the same transaction with the held line moved to its account (QuickBooks' full update, on its SyncToken)
  journal       JournalEntry (a schedule's monthly entry, or a person's adjusting entry)
  delete        the duplicate deleted (only on a person's word)
  close         the books' closing date set (Preferences.AccountingInfoPrefs.BookCloseDate)
  redate        an entry misdated: its date moved to the statement's (full update)
  rebank        an entry in the wrong bank or card account: moved to the account whose statement shows it (full update)
  reamount      an entry a few cents or two swapped digits off: its amount corrected (full update; a person's word only)
  fee           a processor's fee withheld from a deposit: a fee line added to the Deposit, or (for a payment or sales
                receipt banked directly) the fee recorded as an expense of the same day
  deposit       payments waiting in Undeposited Funds banked: a Deposit linking each, less any fee withheld
  restore       an edited entry put back exactly as it was (undoing one of the edits above)
  replace       the client's entry swapped for the right kind (a deposit to income for a payment applied to the open
                invoice; an expense for a bill payment; a card payment booked as an expense for a transfer): the new one
                is made and read back first, then the old one deleted, so a failure leaves both visible, never neither

Every create carries a request id derived from the fix (the same fix always sends the same id), so a retry after a
dropped connection returns the first result instead of a second transaction. Before sending, the caller re-reads the
ledger (prepare.still_needed): if a bank feed or a person recorded the line meanwhile, nothing is sent."""
import hashlib
import json

from ..qbo import ledger_lines


class FixError(Exception):
    pass


def request_id(client_code, fix):
    body = {k: v for k, v in fix.items() if k not in ("auto", "why", "citations") and not k.startswith("_")}
    return "nhb-" + hashlib.sha256(json.dumps([client_code, body], sort_keys=True, default=str).encode()).hexdigest()[:30]


def _amt(c):
    return round(abs(c) / 100, 2)


def _note(fix):
    ln = fix.get("line") or {}
    src = f"statement line {ln['line_id']}" if ln.get("line_id") else ", ".join(fix.get("citations") or [])
    return f"NHB: {src}"[:4000]


def document(fix, types, read_doc=None):
    """(entity, QuickBooks document) for a fix. types: {ledger account: QuickBooks account type}. read_doc(entity, id) reads
    a transaction (for recategorizing, and for the customer or supplier of the invoice or bill being paid)."""
    k = fix["kind"]
    ln = fix.get("line") or {}
    if k == "create":
        acct, to = fix["account"], fix.get("to")
        if not to:
            raise FixError("no account chosen for the line")
        # the tag goes on the line too: QuickBooks' General Ledger shows a line's description, not always the note
        desc = f"{ln.get('description') or ''} · {_note(fix)}".strip(" ·")[:4000]
        parts = [(x["account"], x["amount_cents"]) for x in fix.get("splits") or []] or [(to, abs(ln["amount"]))]
        if sum(v for _, v in parts) != abs(ln["amount"]):
            raise FixError("the split doesn't add up to the line")
        if ln["amount"] > 0 and types.get(acct) != "Credit Card":
            return "Deposit", {"TxnDate": ln["date"], "DepositToAccountRef": {"name": acct}, "PrivateNote": _note(fix),
                               "Line": [{"Amount": _amt(v), "Description": desc, "DetailType": "DepositLineDetail",
                                         "DepositLineDetail": {"AccountRef": {"name": a}}} for a, v in parts]}
        card = types.get(acct) == "Credit Card"
        doc = {"TxnDate": ln["date"], "AccountRef": {"name": acct}, "PaymentType": "CreditCard" if card else "Cash", "PrivateNote": _note(fix),
               "Line": [{"Amount": _amt(v), "Description": desc, "DetailType": "AccountBasedExpenseLineDetail",
                         "AccountBasedExpenseLineDetail": {"AccountRef": {"name": a}}} for a, v in parts]}
        if card and ln["amount"] > 0:
            doc["Credit"] = True                         # a refund onto the card
        return "Purchase", doc
    if k == "transfer":
        return "Transfer", {"TxnDate": fix["date"], "FromAccountRef": {"name": fix["from"]}, "ToAccountRef": {"name": fix["to"]},
                            "Amount": _amt(fix["amount"]), "PrivateNote": _note(fix)}
    if k == "receive":
        inv = read_doc("Invoice", fix["item"]["id"]) if read_doc else {}
        return "Payment", {"TxnDate": ln["date"], "CustomerRef": inv.get("CustomerRef") or {"name": fix["item"].get("name")},
                           "TotalAmt": _amt(ln["amount"]), "DepositToAccountRef": {"name": fix["account"]}, "PrivateNote": _note(fix),
                           "Line": [{"Amount": _amt(ln["amount"]), "LinkedTxn": [{"TxnId": str(fix["item"]["id"]), "TxnType": "Invoice"}]}]}
    if k == "pay_bill":
        bill = read_doc("Bill", fix["item"]["id"]) if read_doc else {}
        card = types.get(fix["account"]) == "Credit Card"
        pay = {"CCAccountRef": {"name": fix["account"]}} if card else {"BankAccountRef": {"name": fix["account"]}}
        return "BillPayment", {"TxnDate": ln["date"], "VendorRef": bill.get("VendorRef") or {"name": fix["item"].get("name")},
                               "PayType": "CreditCard" if card else "Check", ("CreditCardPayment" if card else "CheckPayment"): pay,
                               "TotalAmt": _amt(ln["amount"]), "PrivateNote": _note(fix),
                               "Line": [{"Amount": _amt(ln["amount"]), "LinkedTxn": [{"TxnId": str(fix["item"]["id"]), "TxnType": "Bill"}]}]}
    if k == "recategorize":
        if not fix.get("to"):
            raise FixError("no account chosen")
        doc = json.loads(json.dumps(read_doc(fix["entity"], fix["txn_id"])))
        moved = 0
        for line in doc.get("Line") or []:
            for detail in ("AccountBasedExpenseLineDetail", "DepositLineDetail", "JournalEntryLineDetail"):
                d = line.get(detail)
                if d and (d.get("AccountRef") or {}).get("name") == fix["from"]:
                    d["AccountRef"] = {"name": fix["to"]}
                    moved += 1
        if not moved:
            raise FixError(f"no line of {fix['entity']} {fix['txn_id']} is in {fix['from']} any more")
        doc["PrivateNote"] = (str(doc.get("PrivateNote") or "") + f" | NHB: moved from {fix['from']} to {fix['to']}").strip(" |")[:4000]
        return fix["entity"], doc
    if k == "raw":                                         # a transaction exactly as it was read (putting back a deleted entry)
        return fix["entity"], bare(fix["doc"])
    if k in ("redate", "rebank", "reamount", "restore") or (k == "fee" and fix["entity"] == "Deposit"):
        return fix["entity"], _edit(fix, types, read_doc)
    if k == "fee":                                         # a payment or sales receipt banked directly: the fee as its own expense
        if not fix.get("fee_account"):
            raise FixError("choose the account for the processor's fee")
        return "Purchase", {"TxnDate": fix["date"], "AccountRef": {"name": fix["account"]}, "PaymentType": "Cash",
                            "PrivateNote": f"NHB: processor fee withheld from {fix['entity']} {fix['txn_id']} (statement line {ln.get('line_id')})"[:4000],
                            "Line": [{"Amount": _amt(fix["fee"]), "Description": f"Processor fee · {_note(fix)}"[:4000], "DetailType": "AccountBasedExpenseLineDetail",
                                      "AccountBasedExpenseLineDetail": {"AccountRef": {"name": fix["fee_account"]}}}]}
    if k == "deposit":                                     # payments waiting in Undeposited Funds, banked
        if fix.get("fee") and not fix.get("fee_account"):
            raise FixError("choose the account for the processor's fee")
        if sum(u["amount"] for u in fix["items"]) - (fix.get("fee") or 0) != ln["amount"]:
            raise FixError("the payments less the fee aren't the deposit")
        lines = [{"Amount": _amt(u["amount"]), "Description": f"{u.get('name') or u['entity']} · {_note(fix)}"[:4000],
                  "LinkedTxn": [{"TxnId": str(u["id"]), "TxnType": u["entity"], "TxnLineId": "0"}]} for u in fix["items"]]
        if fix.get("fee"):
            lines.append({"Amount": -_amt(fix["fee"]), "Description": f"Processor fee · {_note(fix)}"[:4000], "DetailType": "DepositLineDetail",
                          "DepositLineDetail": {"AccountRef": {"name": fix["fee_account"]}}})
        return "Deposit", {"TxnDate": ln["date"], "DepositToAccountRef": {"name": fix["account"]}, "PrivateNote": _note(fix), "Line": lines}
    if k == "owner_paid":                                  # a business line from a personal account outside QuickBooks
        if not fix.get("to") or not fix.get("owner"):
            raise FixError("choose the business account (and the owner's equity account)")
        c = abs(ln["amount"])
        memo = f"NHB: statement line {ln['line_id']} ({'paid' if ln['amount'] < 0 else 'received'} by the owner) {ln.get('description') or ''}".strip()
        lines = ([(fix["to"], c), (fix["owner"], -c)] if ln["amount"] < 0 else [(fix["owner"], c), (fix["to"], -c)])
        return "JournalEntry", {"TxnDate": ln["date"], "PrivateNote": memo[:4000],
                                "Line": [{"Amount": _amt(v), "Description": memo[:4000], "DetailType": "JournalEntryLineDetail",
                                          "JournalEntryLineDetail": {"PostingType": "Debit" if v > 0 else "Credit", "AccountRef": {"name": a}}}
                                         for a, v in lines]}
    if k == "journal":
        lines = fix["lines"]
        if sum(x["cents"] for x in lines) != 0:
            raise FixError("the entry doesn't balance")
        return "JournalEntry", {"TxnDate": fix["date"], "PrivateNote": fix.get("memo") or _note(fix),
                                "Line": [{"Amount": _amt(x["cents"]), "Description": x.get("memo") or fix.get("memo") or "", "DetailType": "JournalEntryLineDetail",
                                          "JournalEntryLineDetail": {"PostingType": "Debit" if x["cents"] > 0 else "Credit",
                                                                     "AccountRef": {"name": x["account"]}}} for x in lines]}
    raise FixError(f"no document for a {k} fix")


META = ("Id", "SyncToken", "TotalAmt", "MetaData", "domain", "sparse", "HomeTotalAmt")


def bare(doc):
    """A transaction as read, without what QuickBooks adds itself (so it can be sent back as it was)."""
    return {k: v for k, v in json.loads(json.dumps(doc)).items() if k not in META}


def _edit(fix, types, read_doc):
    k = fix["kind"]
    if k == "restore":
        return bare(fix["doc"])
    read = read_doc(fix["entity"], fix["txn_id"])
    doc = bare(read)
    if read.get("SyncToken") is not None:
        doc["SyncToken"] = read["SyncToken"]              # the version this change was prepared from: a concurrent edit is refused, never overwritten
    note = str(doc.get("PrivateNote") or "")
    if k == "redate":
        doc["TxnDate"] = fix["date"]
        doc["PrivateNote"] = (note + f" | NHB: date {fix['from_date']} to {fix['date']}, as the statement shows").strip(" |")[:4000]
    elif k == "rebank":
        frm, to, ent = fix["from"], fix["to"], fix["entity"]
        card = types.get(to) == "Credit Card"
        if ent == "Purchase":
            if (doc.get("AccountRef") or {}).get("name") != frm:
                raise FixError(f"{ent} {fix['txn_id']} isn't in {frm} any more")
            doc["AccountRef"] = {"name": to}
            doc["PaymentType"] = "CreditCard" if card else ("Check" if doc.get("PaymentType") == "Check" else "Cash")
        elif ent in ("Deposit", "Payment", "SalesReceipt"):
            if card:
                raise FixError("a deposit can't go to a credit card account")
            if ((doc.get("DepositToAccountRef") or {}).get("name") or "") != frm:
                raise FixError(f"{ent} {fix['txn_id']} isn't in {frm} any more")
            doc["DepositToAccountRef"] = {"name": to}
        elif ent == "BillPayment":
            doc.pop("CheckPayment", None)
            doc.pop("CreditCardPayment", None)
            doc["PayType"] = "CreditCard" if card else "Check"
            doc["CreditCardPayment" if card else "CheckPayment"] = {"CCAccountRef": {"name": to}} if card else {"BankAccountRef": {"name": to}}
        else:
            raise FixError(f"a {ent} isn't moved between accounts by the agents")
        doc["PrivateNote"] = (note + f" | NHB: moved from {frm} to {to}, whose statement shows it").strip(" |")[:4000]
    elif k == "reamount":
        new = _amt(fix["to_cents"])
        if fix["entity"] == "Transfer":
            doc["Amount"] = new
        else:
            lines = [ln for ln in doc.get("Line") or [] if ln.get("DetailType") != "SubTotalLineDetail"]
            if len(lines) != 1:
                raise FixError("only an entry with one line has its amount corrected by the agents")
            lines[0]["Amount"] = new
            doc["Line"] = lines
        doc["PrivateNote"] = (note + f" | NHB: amount {_amt(fix['from_cents']):,.2f} to {new:,.2f}, as the statement shows").strip(" |")[:4000]
    elif k == "fee":
        if not fix.get("fee_account"):
            raise FixError("choose the account for the processor's fee")
        doc["Line"] = list(doc.get("Line") or []) + [{"Amount": -_amt(fix["fee"]), "Description": f"Processor fee · {_note(fix)}"[:4000],
                                                     "DetailType": "DepositLineDetail", "DepositLineDetail": {"AccountRef": {"name": fix["fee_account"]}}}]
        doc["PrivateNote"] = (note + f" | NHB: processor fee {_amt(fix['fee']):,.2f} withheld").strip(" |")[:4000]
    return doc


UPDATES = ("recategorize", "redate", "rebank", "reamount", "restore")


def is_update(fix):
    return fix["kind"] in UPDATES or (fix["kind"] == "fee" and fix.get("entity") == "Deposit")


def _gone(exc):
    """Only QuickBooks saying the record isn't there proves a delete; a timeout or any other failure leaves the outcome unknown."""
    from ..qbo import QBOError
    if not isinstance(exc, QBOError):
        return False
    text = str(exc).lower()
    return exc.status in (404,) or "not found" in text or "object not found" in text or '"code": "610"' in text or "code\": \"610" in text


def _delete(adapter, entity, txn_id):
    """Delete and prove it: QuickBooks' own answer (status Deleted), or a read that says the record is gone. Anything else
    is an unknown outcome and an error, never a success (docs/104 A06)."""
    from ..qbo import QBOError
    answer = adapter.delete(entity, txn_id)
    if isinstance(answer, dict) and str(answer.get("status") or "").lower() == "deleted":
        return
    try:
        adapter.read(entity, txn_id)
    except Exception as e:                                # noqa: BLE001
        if _gone(e):
            return
        raise FixError(f"after the delete, QuickBooks couldn't confirm whether {entity} {txn_id} is gone: {e}") from e
    raise FixError(f"{entity} {txn_id} is still there after the delete")


def expected_effect(entity, doc, account_types=None):
    """The ledger lines the document should make: {account: cents}."""
    out = {}
    for a, c, _ in ledger_lines(entity, doc):
        out[a] = out.get(a, 0) + c
    return out


def apply(adapter, fix, client_code):
    """Send one fix to the ledger and read it back. Returns {entity, external_id, request_id, effect}."""
    types = {a["name"]: a["type"] for a in adapter.chart()}
    k = fix["kind"]
    if k == "close":
        got = adapter.set_close_date(fix["date"])
        if got != fix["date"]:
            raise FixError(f"QuickBooks' closing date reads {got}, not {fix['date']}")
        return {"entity": "Preferences", "external_id": "BookCloseDate", "request_id": None, "effect": {"close_date": got}}
    if k == "delete":
        _delete(adapter, fix["entity"], fix["txn_id"])
        return {"entity": fix["entity"], "external_id": str(fix["txn_id"]), "request_id": None, "effect": {"deleted": True}}
    if k == "replace":
        gone = fix["delete"]
        before = bare(adapter.read(gone["entity"], gone["txn_id"]))
        made = apply(adapter, dict(fix["create"], _rid=request_id(client_code, fix)), client_code)
        _delete(adapter, gone["entity"], gone["txn_id"])
        return dict(made, before={"entity": gone["entity"], "doc": before})
    before = bare(adapter.read(fix["entity"], fix["txn_id"])) if is_update(fix) else None
    entity, doc = document(fix, types, adapter.read)
    rid = fix.get("_rid") or request_id(client_code, fix)
    if is_update(fix):
        ext = adapter.update(entity, fix["txn_id"], doc)
    else:
        ext = adapter.create(entity, doc, rid)
    back = adapter.read(entity, ext)
    want = expected_effect(entity, doc, types)
    got = expected_effect(entity, back, types)
    check = {a: c for a, c in want.items() if a in (fix.get("account"), fix.get("to"), fix.get("from"), fix.get("fee_account"))} or want
    if any(got.get(a, 0) != c for a, c in check.items()):
        raise FixError(f"read back {entity} {ext} doesn't show what was sent: {got} against {want}")
    if k == "redate" and back.get("TxnDate") != fix["date"]:
        raise FixError(f"read back {entity} {ext} is dated {back.get('TxnDate')}, not {fix['date']}")
    if k == "rebank" and got.get(fix["from"]):
        raise FixError(f"read back {entity} {ext} is still in {fix['from']}")
    return {"entity": entity, "external_id": str(ext), "request_id": rid, "effect": got, "before": before}


def touched(fix, snap):
    """The accounts a fix changes, so only they are read again: its own accounts, every account of a transaction it edits
    or deletes, and the receivables, payables and undeposited-funds accounts a payment moves."""
    out = {fix.get(k) for k in ("account", "to", "from", "owner", "fee_account")}
    out |= {x["account"] for x in fix.get("lines") or [] if isinstance(x, dict)}      # a journal's lines (a transfer's are line ids)
    for tid in (fix.get("txn_id"), (fix.get("delete") or {}).get("txn_id")):
        if tid:
            out |= {x["account"] for x in snap.get("lines") or [] if str(x["txn_id"]) == str(tid)}
    if fix.get("create"):
        out |= touched(fix["create"], snap)
    if fix.get("kind") == "deposit":
        out |= {a["name"] for a in snap.get("chart") or [] if "undeposited" in a["name"].lower()}
    if fix.get("kind") in ("receive", "pay_bill"):
        out |= {a["name"] for a in snap.get("chart") or [] if a["type"] in ("Accounts Receivable", "Accounts Payable")
                or "undeposited" in a["name"].lower()}
    return {a for a in out if a}
