"""What a person can do in the product, with every control in one place:
- every read and write is scoped by the acting user's firm (another firm's record is "not found");
- every action checks the role's permission (product/auth.py);
- a released, frozen or reopening month refuses runs, approvals and decisions; late evidence for it is kept but held out
  of the books until a person reopens the month (product/authority.py);
- a real client's records aren't processed until the written authorization is recorded, and nothing is processed on an
  unconfirmed accounting basis (product/facts.py);
- an approval names the exact month package (its hash): a stale or changed month can't be approved, and blocking
  findings can't be waived;
- every decision is recorded in the work history with who made it, and time is recorded against stage and person.
Nothing here posts to QuickBooks."""
import calendar
import json
import re
from datetime import date, datetime, timezone

from . import artifacts as artifacts_
from . import auth, db, jobs, storage, wording
from .errors import Conflict, Invalid, NotFound

ENTITY_TYPES = ("unknown", "sole_proprietorship", "single_member_llc", "partnership", "s_corporation", "c_corporation", "other")
# Federal income tax return by entity type, for the tax-workpaper stage. A single-member LLC follows its owner's choice
# (disregarded by default, or an S corporation election), so it stays "confirm" until a person says which.
TAX_FORMS = {"sole_proprietorship": "Form 1040, Schedule C", "partnership": "Form 1065", "s_corporation": "Form 1120-S",
             "c_corporation": "Form 1120", "single_member_llc": "Confirm: Schedule C (disregarded) or Form 1120-S (if it elected)"}
STAGES = ("onboarding", "client_questions", "preparation", "review", "corrections", "support")


def event(conn, ident, action, *, client_id=None, period_id=None, object_type=None, object_id=None, detail=None):
    conn.execute("INSERT INTO work_events (firm_id, client_id, period_id, actor_user_id, actor_kind, action, object_type, object_id, detail) "
                 "VALUES (%s,%s,%s,%s,'user',%s,%s,%s,%s)",
                 (ident.firm_id, client_id, period_id, ident.user_id, action, object_type, object_id, db.jsonb(detail or {})))


# ------------------------------------------------------------------ setup
def bootstrap(conn, firm_name="Demo firm", owner_email=None, owner_name="Owner"):
    """The firm and its owner, created once."""
    from . import config
    email = owner_email or config.LOCAL_OWNER_EMAIL
    u = conn.execute("SELECT * FROM users WHERE email=%s", (email,)).fetchone()
    if u is not None:
        return u
    firm = conn.execute("INSERT INTO firms (name) VALUES (%s) RETURNING id", (firm_name,)).fetchone()
    return conn.execute("INSERT INTO users (firm_id, email, name, role) VALUES (%s,%s,%s,'owner') RETURNING *",
                        (firm["id"], email, owner_name)).fetchone()


# ------------------------------------------------------------------ loading with firm scope
def client(conn, ident, client_id):
    # every route that names a client comes here: a role that can't see the firm's workspace (the client portal's viewer)
    # is refused here once, not route by route (QA audit, QA-003)
    auth.require(ident, "view_workspace")
    row = conn.execute("SELECT * FROM clients WHERE id=%s AND firm_id=%s", (client_id, ident.firm_id)).fetchone()
    if row is None:
        raise NotFound("client not found")
    return row


def period(conn, ident, period_id, client_id=None):
    auth.require(ident, "view_workspace")
    row = conn.execute("SELECT * FROM periods WHERE id=%s AND firm_id=%s", (period_id, ident.firm_id)).fetchone()
    if row is None or (client_id is not None and row["client_id"] != int(client_id)):
        raise NotFound("period not found")
    return row


CLOSED = ("released", "locked", "reopening")


def _unlocked(p):
    if p["status"] == "released":
        raise Conflict(f"{p['label']} is released. Reopen it (owner, with a reason) before changing anything in it.")
    if p["status"] == "locked":
        raise Conflict(f"{p['label']} is locked (an administrative freeze). Unlock it before changing anything in it.")
    if p["status"] == "reopening":
        raise Conflict(f"{p['label']} is being reopened. Wait for it to finish.")


def _authorized(c):
    if c["data_kind"] == "real" and not c["authorization_on_file"]:
        raise Conflict("This is a real client: record the client's written authorization (kit document 02) before uploading or "
                       "processing its records.")


# ------------------------------------------------------------------ clients and periods
DATA_KINDS = {"demo": "R", "blind": "B", "real": "C"}     # the evidence tier each kind of client counts toward
HOW_FOUND = ("client", "reviewer", "later_close", "tax_preparation", "outside_reviewer", "other")


def create_client(conn, ident, *, legal_name, code, data_kind, entity_type="unknown", industry="service", basis=None, basis_source=None):
    auth.require(ident, "manage_clients")
    code = (code or "").strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{2,12}", code):
        raise Invalid("the short code is 2-12 letters or numbers")
    if data_kind not in DATA_KINDS:
        raise Invalid("data_kind is demo, blind or real")
    if entity_type not in ENTITY_TYPES:
        raise Invalid(f"entity type is one of {', '.join(ENTITY_TYPES)}")
    if not (legal_name or "").strip():
        raise Invalid("the legal name is required")
    if len(legal_name.strip()) > 200:                      # QA audit, QA-018: a 100,000-character name was accepted
        raise Invalid("the legal name is at most 200 characters")
    if conn.execute("SELECT 1 FROM clients WHERE firm_id=%s AND code=%s", (ident.firm_id, code)).fetchone():
        raise Conflict(f"a client with code {code} already exists")
    frozen = None
    if data_kind == "blind":                               # the code is frozen before a blind test's inputs arrive
        from .codeprint import fingerprint
        frozen = fingerprint()
    c = conn.execute("INSERT INTO clients (firm_id, code, legal_name, data_kind, entity_type, industry, code_frozen) "
                     "VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING *",
                     (ident.firm_id, code, legal_name.strip(), data_kind, entity_type, industry or "service", frozen)).fetchone()
    event(conn, ident, "client_created", client_id=c["id"], object_type="client", object_id=c["id"],
          detail={"data_kind": data_kind, "entity_type": entity_type})
    from . import facts
    if entity_type != "unknown":
        facts.record(conn, ident, c, "entity_type", entity_type, source=f"set by {ident.name} when the client was opened", confirm=True)
    if basis:                                              # e.g. a demo fixture's declared basis, with its source
        facts.record(conn, ident, c, "basis", basis, source=basis_source or "", confirm=True)
    return client(conn, ident, c["id"])


def update_client(conn, ident, client_id, *, entity_type=None, authorization_note=None, record_authorization=False):
    c = client(conn, ident, client_id)
    if entity_type is not None:
        auth.require(ident, "manage_clients")
        if entity_type not in ENTITY_TYPES or entity_type == "unknown":
            raise Invalid(f"entity type is one of {', '.join(ENTITY_TYPES[1:])}")
        from . import facts
        facts.record(conn, ident, c, "entity_type", entity_type, source=f"set by {ident.name} in the workspace", confirm=True)
        event(conn, ident, "entity_type_set", client_id=c["id"], object_type="client", object_id=c["id"],
              detail={"from": c["entity_type"], "to": entity_type})
    if record_authorization:
        auth.require(ident, "record_authorization")
        note = (authorization_note or "").strip()
        if len(note) < 10:
            raise Invalid("describe the authorization on file (who signed it, when, what it covers)")
        conn.execute("UPDATE clients SET authorization_on_file=true, authorization_note=%s, authorization_by=%s, authorization_at=now() "
                     "WHERE id=%s", (note, ident.user_id, c["id"]))
        event(conn, ident, "authorization_recorded", client_id=c["id"], object_type="client", object_id=c["id"], detail={"note": note})
    return client(conn, ident, client_id)


def create_period(conn, ident, client_id, label):
    auth.require(ident, "upload")
    c = client(conn, ident, client_id)
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", label or ""):
        raise Invalid("a month is written YYYY-MM")
    y, m = int(label[:4]), int(label[5:])
    start, end = date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])
    row = conn.execute("INSERT INTO periods (firm_id, client_id, label, kind, start_date, end_date) VALUES (%s,%s,%s,'month',%s,%s) "
                       "ON CONFLICT (client_id, label) DO NOTHING RETURNING *", (ident.firm_id, c["id"], label, start, end)).fetchone()
    if row is None:
        return conn.execute("SELECT * FROM periods WHERE client_id=%s AND label=%s", (c["id"], label)).fetchone()
    event(conn, ident, "period_opened", client_id=c["id"], period_id=row["id"], object_type="period", object_id=row["id"])
    return row


# ------------------------------------------------------------------ documents
MAX_BYTES = 25 * 1024 * 1024


def upload(conn, ident, client_id, filename, data, *, period_id=None, source="upload"):
    """Store a document once (by its contents) for the client: a handover file (no period) or a month's evidence."""
    auth.require(ident, "upload")
    c = client(conn, ident, client_id)
    _authorized(c)
    p = None
    held = None
    if period_id is not None:
        p = period(conn, ident, period_id, c["id"])
        if p["status"] in CLOSED:                          # late evidence: kept unchanged, held out of the books
            held = f"received after {p['label']} was {'released' if p['status'] == 'released' else p['status']}; held until the month is reopened"
    else:
        closed = conn.execute("SELECT min(label) AS m FROM periods WHERE client_id=%s AND status IN ('released','locked','reopening')",
                              (c["id"],)).fetchone()["m"]
        if closed:                                         # a handover file reaches every month, released ones included
            held = f"a handover file received while {closed} is closed; held until that month is reopened"
    if source not in ("upload", "quickbooks_export", "handover"):
        raise Invalid("unknown source")
    if not data:
        raise Invalid(f"{filename} is empty")
    if len(data) > MAX_BYTES:
        raise Invalid(f"{filename} is larger than 25 MB")
    safe = re.sub(r"[^A-Za-z0-9._ -]", "_", (filename or "upload").split("/")[-1])[:160] or "upload"
    key, digest = storage.store().put(data)
    row = conn.execute(
        "INSERT INTO documents (firm_id, client_id, period_id, filename, sha256, size_bytes, storage_key, source, uploaded_by, admission, held_reason) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (client_id, sha256) DO NOTHING RETURNING *",
        (ident.firm_id, c["id"], p["id"] if p else None, safe, digest, len(data), key, "handover" if p is None and source == "upload" else source,
         ident.user_id, "held" if held else "admitted", held)).fetchone()
    if row is None:                                        # the same file again: one copy, never a second
        return conn.execute("SELECT * FROM documents WHERE client_id=%s AND sha256=%s", (c["id"], digest)).fetchone(), False
    event(conn, ident, "late_evidence_held" if held else "document_uploaded", client_id=c["id"], period_id=p["id"] if p else None,
          object_type="document", object_id=row["id"], detail={"filename": safe, "bytes": len(data), **({"held": held} if held else {})})
    if not held and p is not None:
        from . import requests as product_requests
        product_requests.note_upload(conn, c["id"], p["id"], row["id"])
    if held:
        from . import artifacts
        first = p["label"] if p else conn.execute("SELECT min(label) AS m FROM periods WHERE client_id=%s AND status IN ('released','locked','reopening')",
                                                  (c["id"],)).fetchone()["m"]
        ev = conn.execute("SELECT max(id) AS id FROM work_events WHERE client_id=%s", (c["id"],)).fetchone()["id"]
        artifacts.mark_stale(conn, c["id"], artifacts.months_from(conn, c["id"], first), f"late evidence received: {safe}", ev)
    return row, True


def document_content(conn, ident, document_id):
    auth.require(ident, "view_workspace")
    d = conn.execute("SELECT * FROM documents WHERE id=%s AND firm_id=%s", (document_id, ident.firm_id)).fetchone()
    if d is None:
        raise NotFound("document not found")
    return d, storage.store().get(d["storage_key"])


# ------------------------------------------------------------------ the engine run
def request_run(conn, ident, client_id, period_id):
    """Queue the engine for this client and month. Asking again with the same documents and setup returns the same job."""
    from . import engine
    auth.require(ident, "run_engine")
    c = client(conn, ident, client_id)
    p = period(conn, ident, period_id, c["id"])
    _unlocked(p)
    _authorized(c)
    if c["onboarding"] != "complete":
        raise Conflict("This client is still being onboarded: preparation starts from its onboarding, once it's ready.")
    if not conn.execute("SELECT 1 FROM documents WHERE client_id=%s AND (period_id IS NULL OR period_id=%s) AND admission='admitted'",
                        (c["id"], p["id"])).fetchone():
        raise Conflict("Upload the client's documents first.")
    from . import facts
    facts.require(conn, c["id"], "process", p["start_date"])
    if c.get("close_mode") == "ledger_native":            # the month closes in the client's own ledger (docs/100)
        from . import nativeclose
        return nativeclose.queue(conn, ident, c, p)
    ws = conn.execute("SELECT setup_status FROM engine_workspaces WHERE client_id=%s", (c["id"],)).fetchone()
    ihash = engine.input_hash(conn, c["id"], p["id"], ws["setup_status"] if ws else "none")
    key = f"agents.run:{ident.firm_id}:{p['id']}:{ihash}"
    # one waiting run per month: files arriving one after another fold into the run that hasn't started yet (its inputs
    # are read when it starts), instead of a full run per file. A run already going is never changed: new evidence
    # after it started gets its own run, so nothing it read goes stale unseen.
    waiting = conn.execute("SELECT id FROM jobs WHERE kind='agents.run' AND period_id=%s AND status='queued' AND attempts=0 AND idem_key<>%s "
                           "ORDER BY id DESC LIMIT 1 FOR UPDATE SKIP LOCKED", (p["id"], key)).fetchone()
    if waiting and not conn.execute("SELECT 1 FROM jobs WHERE idem_key=%s", (key,)).fetchone():
        job = conn.execute("UPDATE jobs SET idem_key=%s, payload=%s WHERE id=%s RETURNING *", (key, db.jsonb({"input_hash": ihash, "folded": True}),
                                                                                             waiting["id"])).fetchone()
        return job, False
    job, created = jobs.enqueue(conn, firm_id=ident.firm_id, kind="agents.run", idem_key=key,
                                payload={"input_hash": ihash}, client_id=c["id"], period_id=p["id"], created_by=ident.user_id)
    if created:
        event(conn, ident, "run_requested", client_id=c["id"], period_id=p["id"], object_type="job", object_id=job["id"])
    return job, created


def start_agents_after_upload(conn, ident, client_id, period_id=None):
    """New documents start the agents by themselves (no "run" button needed): for the month they were uploaded to, or
    for handover files the client's latest open month. Returns the job, or None when the agents can't start yet (no
    month, a locked month, a real client without its authorization) and the workspace says why."""
    c = client(conn, ident, client_id)
    p = (period(conn, ident, period_id, c["id"]) if period_id else
         conn.execute("SELECT * FROM periods WHERE client_id=%s AND status<>'locked' ORDER BY label DESC LIMIT 1", (c["id"],)).fetchone())
    if p is None or p["status"] in CLOSED or (c["data_kind"] == "real" and not c["authorization_on_file"]):
        return None
    if c["onboarding"] != "complete":
        return None                                        # a draft: the agents start when preparation starts (product/onboarding.py)
    if not auth.can(ident, "run_engine"):
        return None
    from . import facts
    if facts.blocking(conn, c["id"], "process", p["start_date"]):
        return None                                        # the workspace says what's needed (the basis, say)
    job, _ = request_run(conn, ident, c["id"], p["id"])
    return {"job_id": job["id"], "period_id": p["id"]}


def approve_setup(conn, ident, client_id):
    from . import engine
    auth.require(ident, "approve_setup")
    c = client(conn, ident, client_id)
    _authorized(c)
    ws = conn.execute("SELECT * FROM engine_workspaces WHERE client_id=%s", (c["id"],)).fetchone()
    if ws is None or ws["setup_status"] != "proposed":
        raise Conflict("There's no setup proposal to approve yet. Run the books first.")
    engine.approve_setup(conn, c, f"user:{ident.email}")
    conn.execute("UPDATE engine_workspaces SET setup_status='approved', setup_decided_by=%s, setup_decided_at=now() WHERE client_id=%s",
                 (ident.user_id, c["id"]))
    event(conn, ident, "setup_approved", client_id=c["id"], object_type="setup", object_id=c["id"], detail=ws["setup_proposal"] or {})
    # the agents close the first month still to be prepared on the approved setup, by themselves: months close in order,
    # so a cleanup client starts at its first month, not its latest (docs/87 §18)
    first = conn.execute("SELECT id FROM periods WHERE client_id=%s AND status <> ALL(%s) ORDER BY label LIMIT 1", (c["id"], list(CLOSED))).fetchone()
    start_agents_after_upload(conn, ident, c["id"], first["id"] if first else None)


def job_status(conn, ident, job_id):
    j = conn.execute("SELECT id, kind, status, attempts, max_attempts, error, result, created_at, started_at, finished_at, client_id, period_id "
                     "FROM jobs WHERE id=%s AND firm_id=%s", (job_id, ident.firm_id)).fetchone()
    if j is None:
        raise NotFound("job not found")
    return j


# ------------------------------------------------------------------ decisions
def decide_change_set(conn, ident, change_set_id, *, decision, content_hash, note="", package_hash=None):
    """The change set is a view of the month package (product/authority.py): approving it approves the month package
    that carries it, named by both hashes. Rejecting it records the reason; it never releases or reconciles anything."""
    auth.require(ident, "decide_change_set")
    cs = conn.execute("SELECT * FROM change_sets WHERE id=%s AND firm_id=%s FOR UPDATE", (change_set_id, ident.firm_id)).fetchone()
    if cs is None:
        raise NotFound("change set not found")
    _unlocked(period(conn, ident, cs["period_id"]))
    if decision not in ("approve", "reject"):
        raise Invalid("decision is approve or reject")
    if cs["status"] != "proposed":
        raise Conflict(f"This change set is {cs['status']}; only a proposed change set can be decided.")
    if content_hash != cs["content_hash"]:
        raise Conflict("The change set changed since you opened it. Reload and review the current version.")
    if decision == "reject" and len((note or "").strip()) < 5:
        raise Invalid("say why it's rejected")
    if decision == "approve":
        from . import authority
        if not package_hash:
            raise Conflict("Approve the month package that carries this change set: name the package's hash too (reload the month).")
        p = period(conn, ident, cs["period_id"])
        pkg = authority.current(conn, client(conn, ident, cs["client_id"]), p)[0]
        if pkg.get("change_set") != [cs["version"], cs["content_hash"]]:
            raise Conflict("This change set isn't the one in the month's current package. Reload and review the current version.")
        authority.approve_month(conn, ident, cs["client_id"], cs["period_id"], package_hash, release_when_matched=False, note=note)
        return conn.execute("SELECT * FROM change_sets WHERE id=%s", (cs["id"],)).fetchone()
    status = "rejected"
    conn.execute("UPDATE change_sets SET status=%s, decided_by=%s, decided_at=now(), decision_note=%s, approved_hash=%s WHERE id=%s",
                 (status, ident.user_id, (note or "").strip() or None, cs["content_hash"] if status == "approved" else None, cs["id"]))
    event(conn, ident, f"change_set_{status}", client_id=cs["client_id"], period_id=cs["period_id"], object_type="change_set",
          object_id=cs["id"], detail={"content_hash": cs["content_hash"], "version": cs["version"], "note": note})
    return conn.execute("SELECT * FROM change_sets WHERE id=%s", (cs["id"],)).fetchone()


def decide_exception(conn, ident, exception_id, *, decision, note, seen_run_id=None):
    """seen_run_id: the run the person saw the finding on. A newer run may have changed it (its message, its severity),
    so a decision made on the older one is refused with a reload, never applied to what the person didn't see."""
    auth.require(ident, "decide_exception")
    e = conn.execute("SELECT * FROM exceptions WHERE id=%s AND firm_id=%s FOR UPDATE", (exception_id, ident.firm_id)).fetchone()
    if e is None:
        raise NotFound("exception not found")
    if seen_run_id is not None and int(seen_run_id) != e["run_id"]:
        raise Conflict("This finding changed since you opened it (a newer run). Reload to see the current version.")
    _unlocked(period(conn, ident, e["period_id"]))
    if decision not in ("resolve", "waive", "reopen"):
        raise Invalid("decision is resolve, waive or reopen")
    if decision != "reopen" and len((note or "").strip()) < 5:
        raise Invalid("record what was done or why it's accepted")
    if decision in ("resolve", "waive") and e["status"] != "open":
        raise Conflict(f"This finding is {e['status']} now, not open. Reload to see the current version.")
    if decision == "reopen" and e["status"] not in ("resolved", "waived"):
        raise Conflict(f"This finding is {e['status']}: only a resolved or waived finding is reopened.")
    if decision == "waive" and e["severity"] in NON_WAIVABLE_SEVERITIES:
        raise Conflict("A blocking finding can't be waived: it stops the month for a reason (a missing statement, a difference, "
                       "unreadable evidence). Fix it with evidence; the next run clears it.")
    if decision == "waive" and e["code"] in NON_WAIVABLE_CODES:
        raise Conflict("This kind of finding can't be waived; it has to be fixed with evidence.")
    # a blocking finding a person has dealt with is "addressed": the next run confirms it (clears it) or opens it again
    status = {"resolve": "addressed" if e["severity"] == "blocker" else "resolved", "waive": "waived", "reopen": "open"}[decision]
    conn.execute("UPDATE exceptions SET status=%s, resolution=%s, resolved_by=%s, resolved_at=%s, decided_on_run=%s WHERE id=%s",
                 (status, (note or "").strip() or None, ident.user_id if status != "open" else None,
                  datetime.now(timezone.utc) if status != "open" else None, e["run_id"], e["id"]))
    event(conn, ident, f"exception_{status}", client_id=e["client_id"], period_id=e["period_id"], object_type="exception", object_id=e["id"],
          detail={"code": e["code"], "note": note})


# blocking findings never close by a person's say-so; these codes can't be waived at any severity: the engine raises them
# for missing or unreadable evidence, differences that don't tie, and changes held for a released month
NON_WAIVABLE_SEVERITIES = ("blocker",)
NON_WAIVABLE_CODES = ("released_period_change_held", "reconciliation_difference", "statement_missing", "unreadable_document",
                      "settlement_unexplained")


# ------------------------------------------------------------------ time
def start_timer(conn, ident, client_id, period_id, stage):
    auth.require(ident, "record_time")
    c = client(conn, ident, client_id)
    p = period(conn, ident, period_id, c["id"])
    if stage not in STAGES:
        raise Invalid(f"stage is one of {', '.join(STAGES)}")
    if conn.execute("SELECT 1 FROM time_entries WHERE user_id=%s AND source='timer' AND ended_at IS NULL", (ident.user_id,)).fetchone():
        raise Conflict("A timer is already running. Stop it first.")
    return conn.execute("INSERT INTO time_entries (firm_id, client_id, period_id, user_id, stage, started_at, source) "
                        "VALUES (%s,%s,%s,%s,%s,now(),'timer') RETURNING *", (ident.firm_id, c["id"], p["id"], ident.user_id, stage)).fetchone()


def stop_timer(conn, ident, note=""):
    t = conn.execute("SELECT * FROM time_entries WHERE user_id=%s AND source='timer' AND ended_at IS NULL", (ident.user_id,)).fetchone()
    if t is None:
        raise Conflict("No timer is running.")
    return conn.execute("UPDATE time_entries SET ended_at=now(), minutes=GREATEST(1, CEIL(EXTRACT(EPOCH FROM (now() - started_at)) / 60.0))::int, "
                        "note=%s WHERE id=%s RETURNING *", ((note or "").strip() or None, t["id"])).fetchone()


def add_time(conn, ident, client_id, period_id, stage, minutes, note="", party="buyer"):
    """party: whose effort it is (the firm's people, ours as the provider, or the client's owner, product/effort.py)."""
    auth.require(ident, "record_time")
    if party not in ("buyer", "provider", "client_owner"):
        raise Invalid("party is buyer, provider or client_owner")
    c = client(conn, ident, client_id)
    p = period(conn, ident, period_id, c["id"])
    if stage not in STAGES:
        raise Invalid(f"stage is one of {', '.join(STAGES)}")
    try:
        minutes = int(minutes)
    except (TypeError, ValueError):
        raise Invalid("minutes is a whole number")
    if not 1 <= minutes <= 600:
        raise Invalid("minutes is between 1 and 600")
    return conn.execute("INSERT INTO time_entries (firm_id, client_id, period_id, user_id, stage, minutes, note, source, party) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s,'manual',%s) RETURNING *",
                        (ident.firm_id, c["id"], p["id"], ident.user_id, stage, minutes, (note or "").strip() or None, party)).fetchone()


# ------------------------------------------------------------------ the period's lock
def lock_period(conn, ident, period_id, reason=""):
    """An administrative freeze: nothing in the month changes until it's unlocked. It claims nothing about the books (it
    isn't a release: product/authority.release_month is), and it's never counted as one."""
    auth.require(ident, "lock_period")
    p = period(conn, ident, period_id)
    _unlocked(p)
    if len((reason or "").strip()) < 5:
        raise Invalid("say why the month is frozen (a freeze isn't a release)")
    conn.execute("UPDATE periods SET status='locked', locked_at=now(), locked_by=%s, lock_reason=%s WHERE id=%s",
                 (ident.user_id, reason.strip(), p["id"]))
    event(conn, ident, "period_locked", client_id=p["client_id"], period_id=p["id"], object_type="period", object_id=p["id"],
          detail={"reason": reason.strip()})


def unlock_period(conn, ident, period_id, note):
    auth.require(ident, "unlock_period")
    p = period(conn, ident, period_id)
    if p["status"] == "released":
        raise Conflict("A released month is reopened, not unlocked (owner, with a reason).")
    if p["status"] != "locked":
        raise Conflict("The period isn't locked.")
    if len((note or "").strip()) < 5:
        raise Invalid("say why the period is being unlocked")
    conn.execute("UPDATE periods SET status='in_review', locked_at=NULL, locked_by=NULL, lock_reason=NULL WHERE id=%s", (p["id"],))
    event(conn, ident, "period_unlocked", client_id=p["client_id"], period_id=p["id"], object_type="period", object_id=p["id"],
          detail={"note": note})


# ------------------------------------------------------------------ the review package
def request_package(conn, ident, client_id, period_id):
    auth.require(ident, "build_package")
    c = client(conn, ident, client_id)
    p = period(conn, ident, period_id, c["id"])
    run = conn.execute("SELECT * FROM runs WHERE period_id=%s AND status IN ('complete','needs_information') ORDER BY id DESC LIMIT 1",
                       (p["id"],)).fetchone()
    if run is None:
        raise Conflict("Run the books for this month first.")
    state = conn.execute("SELECT (SELECT max(id) FROM work_events WHERE period_id=%s) AS ev, (SELECT max(id) FROM time_entries WHERE period_id=%s) AS te",
                         (p["id"], p["id"])).fetchone()
    job, created = jobs.enqueue(conn, firm_id=ident.firm_id, kind="package.build",
                                idem_key=f"package.build:{p['id']}:{run['id']}:{state['ev']}:{state['te']}",
                                payload={"run_id": run["id"]}, client_id=c["id"], period_id=p["id"], created_by=ident.user_id)
    if created:
        event(conn, ident, "package_requested", client_id=c["id"], period_id=p["id"], object_type="job", object_id=job["id"])
    return job, created


# ------------------------------------------------------------------ what the screens show
def portfolio(conn, ident):
    auth.require(ident, "view_workspace")
    rows = conn.execute(
        "SELECT c.*, "
        " (SELECT row_to_json(p) FROM (SELECT id, label, status FROM periods WHERE client_id=c.id ORDER BY label DESC LIMIT 1) p) AS latest_period, "
        " (SELECT count(*) FROM documents WHERE client_id=c.id) AS documents, "
        " (SELECT count(*) FROM exceptions WHERE client_id=c.id AND status='open' AND severity='blocker') AS open_blockers, "
        " (SELECT count(*) FROM exceptions WHERE client_id=c.id AND status='open' AND severity<>'blocker') AS open_review, "
        " (SELECT count(*) FROM change_sets WHERE client_id=c.id AND status='proposed') AS proposed_change_sets, "
        " (SELECT count(*) FROM client_requests WHERE client_id=c.id AND status='open') AS open_requests, "
        " (SELECT COALESCE(sum(minutes),0) FROM time_entries WHERE client_id=c.id) AS minutes, "
        " (SELECT status FROM runs WHERE client_id=c.id ORDER BY id DESC LIMIT 1) AS last_run_status, "
        " (SELECT setup_status FROM engine_workspaces WHERE client_id=c.id) AS setup_status, "
        " (SELECT status FROM jobs WHERE client_id=c.id ORDER BY id DESC LIMIT 1) AS last_job_status, "
        # the client's latest onboarding: a cancelled one is shown with its reason, and the owner can restart it (docs/87 §17)
        " (SELECT row_to_json(o) FROM (SELECT id, status, version, step, cancel_reason FROM onboarding_sessions WHERE client_id=c.id "
        "  ORDER BY id DESC LIMIT 1) o) AS latest_onboarding "
        "FROM clients c WHERE c.firm_id=%s ORDER BY c.legal_name", (ident.firm_id,)).fetchall()
    out = []
    for r in rows:
        r = dict(r)
        r["stage"] = _stage(r)
        r["tax_form"] = TAX_FORMS.get(r["entity_type"])
        out.append(r)
    return out


def _stage(r):
    if r["data_kind"] == "real" and not r["authorization_on_file"]:
        return {"key": "authorization", "label": "Needs written authorization"}
    if not r["documents"]:
        return {"key": "collecting", "label": "Waiting for documents"}
    if r["last_job_status"] in ("queued", "running"):
        return {"key": "working", "label": "Engine running"}
    if r["setup_status"] == "proposed":
        return {"key": "setup", "label": "Setup to approve"}
    if r["last_run_status"] is None:
        return {"key": "ready", "label": "Ready to run"}
    if r["open_blockers"] or r["open_requests"]:
        return {"key": "information", "label": "Missing information"}
    if r["proposed_change_sets"] or r["open_review"]:
        return {"key": "review", "label": "Ready for review"}
    if (r["latest_period"] or {}).get("status") == "released":
        return {"key": "done", "label": "Month released"}
    if (r["latest_period"] or {}).get("status") == "locked":
        return {"key": "frozen", "label": "Month frozen"}
    return {"key": "review", "label": "Ready for review"}


def workspace(conn, ident, client_id, period_id):
    auth.require(ident, "view_workspace")
    c = client(conn, ident, client_id)
    p = period(conn, ident, period_id, c["id"])
    pid = p["id"]
    docs = conn.execute("SELECT d.id, d.filename, d.size_bytes, d.source, d.uploaded_at, d.period_id, d.admission, d.held_reason, "
                        "d.admitted_at, u.name AS uploaded_by "
                        "FROM documents d LEFT JOIN users u ON u.id=d.uploaded_by "
                        "WHERE d.client_id=%s AND (d.period_id IS NULL OR d.period_id=%s) ORDER BY d.period_id NULLS FIRST, d.id", (c["id"], pid)).fetchall()
    ws = conn.execute("SELECT setup_status, setup_proposal, setup_decided_at, (SELECT name FROM users WHERE id=setup_decided_by) AS decided_by "
                      "FROM engine_workspaces WHERE client_id=%s", (c["id"],)).fetchone()
    run = conn.execute("SELECT * FROM runs WHERE period_id=%s ORDER BY id DESC LIMIT 1", (pid,)).fetchone()
    job = conn.execute("SELECT id, kind, status, attempts, max_attempts, error, created_at, finished_at FROM jobs "
                       "WHERE period_id=%s AND kind IN ('agents.run','engine.close') ORDER BY id DESC LIMIT 1", (pid,)).fetchone()
    exc = conn.execute("SELECT e.*, u.name AS resolved_by_name FROM exceptions e LEFT JOIN users u ON u.id=e.resolved_by "
                       "WHERE e.period_id=%s ORDER BY CASE e.status WHEN 'open' THEN 0 ELSE 1 END, "
                       "CASE e.severity WHEN 'blocker' THEN 0 WHEN 'review' THEN 1 ELSE 2 END, e.id", (pid,)).fetchall()
    ev = _evidence(conn, "exception", [e["id"] for e in exc])
    cs = conn.execute("SELECT cs.*, u.name AS decided_by_name FROM change_sets cs LEFT JOIN users u ON u.id=cs.decided_by "
                      "WHERE cs.period_id=%s ORDER BY cs.version DESC LIMIT 1", (pid,)).fetchone()
    lines = conn.execute("SELECT * FROM change_lines WHERE change_set_id=%s ORDER BY seq", (cs["id"],)).fetchall() if cs else []
    lev = _evidence(conn, "change_line", [ln["id"] for ln in lines])
    corrections = []
    for ln in lines:
        if not corrections or corrections[-1]["key"] != ln["correction_key"]:
            corrections.append({"key": ln["correction_key"], "kind": ln["kind"], "date": ln["entry_date"], "why": wording.text(ln["why"]),
                                "lines": [], "evidence": []})
        g = corrections[-1]
        g["lines"].append({k: ln[k] for k in ("id", "period_label", "account", "account_name", "amount_cents")})
        for e in lev.get(ln["id"], []):
            if e not in g["evidence"]:
                g["evidence"].append(e)
    time_rows = conn.execute("SELECT t.*, u.name AS user_name FROM time_entries t JOIN users u ON u.id=t.user_id WHERE t.period_id=%s "
                             "ORDER BY t.id DESC", (pid,)).fetchall()
    events = conn.execute("SELECT w.action, w.object_type, w.object_id, w.detail, w.at, w.actor_kind, u.name AS actor "
                          "FROM work_events w LEFT JOIN users u ON u.id=w.actor_user_id WHERE w.client_id=%s AND (w.period_id=%s OR w.period_id IS NULL) "
                          "ORDER BY w.id DESC LIMIT 100", (c["id"], pid)).fetchall()
    packages = conn.execute("SELECT r.id, r.created_at, r.sha256, u.name AS created_by FROM review_packages r LEFT JOIN users u ON u.id=r.created_by "
                            "WHERE r.period_id=%s ORDER BY r.id DESC", (pid,)).fetchall()
    running_timer = conn.execute("SELECT id, stage, started_at, period_id FROM time_entries WHERE user_id=%s AND source='timer' AND ended_at IS NULL",
                                 (ident.user_id,)).fetchone()
    return {
        "client": {**dict(c), "tax_form": TAX_FORMS.get(c["entity_type"])},
        "period": dict(p),
        "periods": conn.execute("SELECT id, label, status FROM periods WHERE client_id=%s ORDER BY label DESC", (c["id"],)).fetchall(),
        "documents": docs,
        "setup": dict(ws) if ws else {"setup_status": "none"},
        "run": dict(run) if run else None,
        "job": dict(job) if job else None,
        "exceptions": [{**dict(e), "message": wording.text(e["message"]), "evidence": ev.get(e["id"], [])} for e in exc],
        "change_set": ({**dict(cs), "corrections": corrections} if cs else None),
        "reconciliations": conn.execute("SELECT * FROM reconciliations WHERE period_id=%s ORDER BY account", (pid,)).fetchall(),
        "requests": [{**dict(r), "what": wording.text(r["what"]), "why": wording.text(r["why"])} for r in conn.execute(
            "SELECT * FROM client_requests WHERE period_id=%s ORDER BY CASE status WHEN 'open' THEN 0 ELSE 1 END, id", (pid,)).fetchall()],
        "time": {"entries": time_rows, "total_minutes": sum(t["minutes"] or 0 for t in time_rows),
                 "by_stage": {s: sum(t["minutes"] or 0 for t in time_rows if t["stage"] == s) for s in STAGES},
                 "running": running_timer},
        "events": events,
        "packages": packages,
        "escapes": escapes(conn, p["id"]),
        "facts": _facts_view(conn, c, p),
        "artifacts": artifacts_.for_period(conn, pid),
        "operations": conn.execute("SELECT id, kind, state, error, created_at FROM operations WHERE period_id=%s AND state<>'done' "
                                   "ORDER BY created_at DESC", (pid,)).fetchall(),
        "packages_approved": conn.execute("SELECT m.id, m.version, m.package_hash, m.status, m.approved_at, m.released_at, m.ended_reason, "
                                          "u.name AS approved_by FROM month_packages m JOIN users u ON u.id=m.approved_by WHERE m.period_id=%s "
                                          "ORDER BY m.version DESC", (pid,)).fetchall(),
        "permissions": {k: auth.can(ident, k) for k in auth.PERMISSIONS},
    }


def _facts_view(conn, c, p):
    from . import facts
    return {"in_force": facts.in_force(conn, c["id"], p["start_date"]),
            "holds": {op: facts.blocking(conn, c["id"], op, p["start_date"]) for op in ("process", "approve_month", "release", "tax_handoff")}}


def _evidence(conn, subject_type, ids):
    if not ids:
        return {}
    rows = conn.execute("SELECT e.subject_id, e.document_id, e.row_no, e.record_type, e.excerpt, e.role, d.filename "
                        "FROM evidence_links e LEFT JOIN documents d ON d.id=e.document_id "
                        "WHERE e.subject_type=%s AND e.subject_id = ANY(%s) ORDER BY e.id", (subject_type, list(ids))).fetchall()
    out = {}
    for r in rows:
        out.setdefault(r["subject_id"], []).append({k: r[k] for k in ("document_id", "filename", "row_no", "record_type", "excerpt", "role")})
    return out


def record_escape(conn, ident, client_id, period_id, *, severity, how_found, description, found_on=None, account=None,
                  amount_cents=None, minutes_to_fix=None):
    """An error found after the month was locked. While a month is open, a problem is fixed in its review instead."""
    auth.require(ident, "decide_exception")
    c = client(conn, ident, client_id)
    p = period(conn, ident, period_id, c["id"])
    if p["status"] != "released":
        raise Conflict("This month isn't released: fix the problem in its review. An escape is an error found after release.")
    if severity not in ("minor", "material"):
        raise Invalid("severity is minor or material")
    if how_found not in HOW_FOUND:
        raise Invalid(f"how it was found is one of {', '.join(HOW_FOUND)}")
    if len((description or "").strip()) < 10:
        raise Invalid("describe the error (at least 10 characters)")
    for name, v in (("amount", amount_cents), ("minutes to fix", minutes_to_fix)):
        if v is not None and not isinstance(v, int):
            raise Invalid(f"{name} is a whole number")
    row = conn.execute("INSERT INTO escapes (firm_id, client_id, period_id, found_on, how_found, severity, description, account, "
                       "amount_cents, minutes_to_fix, recorded_by) VALUES (%s,%s,%s,COALESCE(%s, CURRENT_DATE),%s,%s,%s,%s,%s,%s,%s) RETURNING *",
                       (ident.firm_id, c["id"], p["id"], found_on, how_found, severity, description.strip(), account or None,
                        amount_cents, minutes_to_fix, ident.user_id)).fetchone()
    event(conn, ident, "escape_recorded", client_id=c["id"], period_id=p["id"], object_type="escape", object_id=row["id"],
          detail={"severity": severity, "how_found": how_found})
    return row


def evaluation(conn, ident):
    """The firm's measures by evidence tier (R, B, C), never mixed: client-months, escapes, proposal decisions, human
    minutes by stage, and for blind tests whether every run used the frozen code."""
    auth.require(ident, "view_workspace")
    tiers = {}
    for kind, tier in DATA_KINDS.items():
        f = (ident.firm_id, kind)
        months = conn.execute("SELECT count(DISTINCT p.id) AS run, count(DISTINCT p.id) FILTER (WHERE p.status='released') AS locked "
                              "FROM periods p JOIN clients c ON c.id=p.client_id JOIN runs r ON r.period_id=p.id AND r.status<>'awaiting_setup' "
                              "WHERE c.firm_id=%s AND c.data_kind=%s", f).fetchone()
        esc = conn.execute("SELECT count(*) AS n, count(*) FILTER (WHERE e.severity='material') AS material, "
                           "coalesce(sum(e.minutes_to_fix), 0) AS minutes FROM escapes e JOIN clients c ON c.id=e.client_id "
                           "WHERE c.firm_id=%s AND c.data_kind=%s", f).fetchone()
        cs = conn.execute("SELECT cs.status, count(*) AS n, coalesce(sum((SELECT count(DISTINCT correction_key) FROM change_lines l "
                          "WHERE l.change_set_id=cs.id)), 0) AS corrections FROM change_sets cs JOIN clients c ON c.id=cs.client_id "
                          "WHERE c.firm_id=%s AND c.data_kind=%s GROUP BY cs.status", f).fetchall()
        by = {r["status"]: r for r in cs}
        approved, rejected = (by.get("approved") or {}).get("n", 0), (by.get("rejected") or {}).get("n", 0)
        minutes = {r["stage"]: int(r["m"]) for r in conn.execute(
            "SELECT t.stage, sum(t.minutes) AS m FROM time_entries t JOIN clients c ON c.id=t.client_id "
            "WHERE c.firm_id=%s AND c.data_kind=%s AND t.minutes IS NOT NULL GROUP BY t.stage", f).fetchall()}
        timed = conn.execute("SELECT count(DISTINCT t.period_id) AS n FROM time_entries t JOIN clients c ON c.id=t.client_id "
                             "WHERE c.firm_id=%s AND c.data_kind=%s AND t.minutes IS NOT NULL", f).fetchone()["n"]
        out = {"tier": tier, "kind": kind, "client_months": months["run"], "locked_months": months["locked"],
               "escapes": esc["n"], "material_escapes": esc["material"], "escape_minutes": int(esc["minutes"]),
               "escapes_per_locked_month": round(esc["n"] / months["locked"], 3) if months["locked"] else None,
               "change_sets": {"approved": approved, "rejected": rejected,
                               "superseded_before_a_decision": (by.get("superseded") or {}).get("n", 0),
                               "waiting": (by.get("proposed") or {}).get("n", 0),
                               "corrections_approved": int((by.get("approved") or {}).get("corrections", 0))},
               "approval_rate": round(approved / (approved + rejected), 3) if approved + rejected else None,
               "minutes_by_stage": minutes, "minutes_total": sum(minutes.values()), "timed_client_months": timed,
               "minutes_per_timed_month": round(sum(minutes.values()) / timed, 1) if timed else None}
        if kind == "blind":
            runs = conn.execute("SELECT c.code, c.code_frozen, r.summary->>'code_fingerprint' AS used FROM runs r JOIN clients c "
                                "ON c.id=r.client_id WHERE c.firm_id=%s AND c.data_kind='blind'", (ident.firm_id,)).fetchall()
            out["runs_on_changed_code"] = sorted({r["code"] for r in runs if r["used"] != r["code_frozen"]})
        tiers[tier] = out
    return {"tiers": tiers, "unsafe_events": None,
            "notes": {"R": "The engine's own fixtures: a regression check, never accuracy or time saved.",
                      "B": "Blind tests: inputs written independently and the code frozen first. A client whose runs used changed "
                           "code isn't a blind result.",
                      "C": "Real clients with their written authorization. Measures here need an outside reviewer before they're "
                           "quoted.",
                      "unsafe_events": "Not measured yet: nothing writes to a ledger from the workspace (posting is backlog B-9)."}}


def escapes(conn, period_id):
    return conn.execute("SELECT e.*, u.name AS recorded_by_name FROM escapes e JOIN users u ON u.id=e.recorded_by "
                        "WHERE e.period_id=%s ORDER BY e.id", (period_id,)).fetchall()


def _latest_run(conn, period_id):
    return conn.execute("SELECT id, status, statements, created_at FROM runs WHERE period_id=%s AND status IN ('complete','needs_information') "
                        "ORDER BY id DESC LIMIT 1", (period_id,)).fetchone()


def statements(conn, ident, client_id, period_id):
    """The month's profit and loss and balance sheet from the latest run (product/statements.py), with its checks."""
    from . import statements as st
    auth.require(ident, "view_workspace")
    c = client(conn, ident, client_id)
    p = period(conn, ident, period_id, c["id"])
    run = _latest_run(conn, p["id"])
    if run is None or not (run["statements"] or {}).get("accounts"):
        return {"available": False}
    out = st.build(run["statements"], st.activity(conn, run["id"], p["label"]), p["label"])
    # never shown as current when an input changed since (late evidence, a reopen, a changed fact)
    art = artifacts_.status_for(conn, p["id"], "statements")
    return {"available": True, "run_id": run["id"], "run_created_at": run["created_at"], "artifact": art, **out}


def account_detail(conn, ident, client_id, period_id, account, scope="month"):
    """Drill-down: the entries on one account that make up its statement figure for the month (or the year to date):
    recorded entries with the ledger rows they came from, and proposed changes with the change set's evidence."""
    from . import statements as st
    auth.require(ident, "view_workspace")
    c = client(conn, ident, client_id)
    p = period(conn, ident, period_id, c["id"])
    run = _latest_run(conn, p["id"])
    if run is None:
        raise NotFound("Run the books for this month first.")
    if scope not in ("month", "year"):
        raise Invalid("scope is month or year")
    end = st.month_end(p["label"])
    start = date(end.year, end.month, 1) if scope == "month" else date(end.year, 1, 1)
    acct = next((a for a in (run["statements"] or {}).get("accounts", []) if a["account"] == account), None)
    if acct is None:
        raise NotFound("That account isn't in this client's chart.")
    rows = conn.execute("SELECT e.id, e.basis, e.entry_key, e.entry_date, e.kind, e.memo, sum(l.amount_cents)::bigint AS amount_cents "
                        "FROM ledger_entries e JOIN ledger_entry_lines l ON l.entry_id=e.id WHERE e.run_id=%s AND l.account=%s "
                        "AND e.entry_date BETWEEN %s AND %s GROUP BY e.id ORDER BY e.entry_date, e.basis DESC, e.id",
                        (run["id"], account, start, end)).fetchall()
    ev = _evidence(conn, "entry", [r["id"] for r in rows if r["basis"] == "recorded"])
    keys = sorted({r["entry_key"] for r in rows if r["basis"] == "proposed"})
    why, change_ev = {}, {}
    if keys:
        lines = conn.execute("SELECT cl.id, cl.correction_key, cl.why FROM change_lines cl JOIN change_sets cs ON cs.id=cl.change_set_id "
                             "WHERE cs.period_id=%s AND cs.status<>'superseded' AND cl.correction_key = ANY(%s) ORDER BY cs.version DESC, cl.seq",
                             (p["id"], keys)).fetchall()
        line_ev = _evidence(conn, "change_line", [x["id"] for x in lines])
        for x in lines:
            why.setdefault(x["correction_key"], x["why"])
            seen = change_ev.setdefault(x["correction_key"], [])
            for e in line_ev.get(x["id"], []):
                if e not in seen:
                    seen.append(e)
    entries = [{**dict(r), "why": why.get(r["entry_key"]) if r["basis"] == "proposed" else None,
                "evidence": ev.get(r["id"], []) if r["basis"] == "recorded" else change_ev.get(r["entry_key"], [])} for r in rows]
    return {"account": account, "name": acct["name"], "type": acct["type"], "scope": scope, "from": start, "to": end,
            "total_cents": sum(int(r["amount_cents"]) for r in rows),
            "recorded_cents": sum(int(r["amount_cents"]) for r in rows if r["basis"] == "recorded"),
            "proposed_cents": sum(int(r["amount_cents"]) for r in rows if r["basis"] == "proposed"), "entries": entries}


def settlement(conn, ident, client_id, period_id):
    """The month's settlement-to-bank bridge from the latest run: batches, deposits, what's in transit or unexplained,
    the proposed entries (review only) and the rules behind them with their review status."""
    from ops.books.rule_register import rule
    auth.require(ident, "view_workspace")
    c = client(conn, ident, client_id)
    p = period(conn, ident, period_id, c["id"])
    run = conn.execute("SELECT id, created_at, summary FROM runs WHERE period_id=%s AND summary ? 'settlement_bridge' ORDER BY id DESC LIMIT 1",
                       (p["id"],)).fetchone()
    if run is None:
        return {"available": False}
    report = run["summary"]["settlement_bridge"]
    from . import rulereview                                  # the review status a person recorded (product/rulereview.py)
    return {"available": True, "run_id": run["id"], "run_created_at": run["created_at"], "artifact": artifacts_.status_for(conn, p["id"], "settlement_bridge"),
            **report, "register": {r: {**rule(r), **rulereview.review_for(conn, c["firm_id"], r)} for r in (report.get("rules") or {})}}


def me(conn, ident):
    firm = conn.execute("SELECT name FROM firms WHERE id=%s", (ident.firm_id,)).fetchone()
    u = conn.execute("SELECT display_mode FROM users WHERE id=%s", (ident.user_id,)).fetchone()
    return {"id": ident.user_id, "name": ident.name, "email": ident.email, "role": ident.role, "firm": firm["name"],
            "display_mode": u["display_mode"] if u else "guided",
            "permissions": {k: auth.can(ident, k) for k in auth.PERMISSIONS}}


def _jsonable(obj):
    return json.loads(json.dumps(obj, default=str))
