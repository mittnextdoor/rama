"""Durable background jobs in Postgres (docs/82 §7).

- enqueue: one row per unit of work. The idempotency key is built from the work's inputs and namespaced by firm, so
  asking twice for the same work returns the existing job instead of doing it again.
- claim: a worker takes the oldest ready job with FOR UPDATE SKIP LOCKED, under a lease. Work on the same client is
  serialized: a client's job isn't claimed while another of its jobs holds a live lease (its engine file and books are
  one unit), and an advisory lock keeps two workers from claiming two of one client's jobs at the same moment. A job
  whose worker died (its lease expired) is claimed again.
- heartbeat: while a handler runs, a thread extends the lease. A worker that loses the lease (it stalled, and another
  worker took the job) can't finish it: succeed and fail only apply to the worker that holds the lease, and its
  Postgres writes roll back with the refused finish.
- finish: success records the result; a failure retries with backoff (30 s, 60 s, 120 s, ...) and becomes dead after
  max_attempts, with the error kept. A Throttled failure (an integration asked us to slow down) waits as asked without
  using up an attempt, up to MAX_THROTTLES times. Nothing fails silently.

A queue's idempotency doesn't make an external write happen exactly once: the engine's posting keeps its own intent
records, stable request ids and read-back (ops/books/manifest.py) for that.

Handlers are registered by kind (product/engine.py registers agents.run, formerly engine.close, and product/package.py package.build)."""
import os
import socket
import threading
import traceback

from . import db

HANDLERS = {}
LEASE_SECONDS = 600
BACKOFF_SECONDS = 30
MAX_THROTTLES = 10
HEARTBEAT_SECONDS = None                                  # default: a third of the lease


def handler(kind):
    def register(fn):
        HANDLERS[kind] = fn
        return fn
    return register


class Permanent(Exception):
    """A failure retrying can't fix (bad input, a locked period): the job goes straight to dead with this message."""


class Throttled(Exception):
    """An integration asked us to slow down (HTTP 429, say): wait retry_after seconds, without using up an attempt."""

    def __init__(self, message, retry_after=60):
        super().__init__(message)
        self.retry_after = max(1, int(retry_after))


class LeaseLost(Exception):
    """This worker no longer holds the job's lease: another worker has it. Nothing this worker did is committed."""


def enqueue(conn, *, firm_id, kind, idem_key, payload=None, client_id=None, period_id=None, created_by=None, max_attempts=3):
    """Returns (job, created). An existing job with the same key is returned unchanged. Keys are namespaced by firm."""
    if not idem_key.startswith(f"{kind}:{firm_id}:"):
        idem_key = f"{kind}:{firm_id}:{idem_key.split(':', 1)[1] if idem_key.startswith(kind + ':') else idem_key}"
    row = conn.execute(
        "INSERT INTO jobs (firm_id, client_id, period_id, kind, idem_key, payload, created_by, max_attempts) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (idem_key) DO NOTHING RETURNING *",
        (firm_id, client_id, period_id, kind, idem_key, db.jsonb(payload or {}), created_by, max_attempts)).fetchone()
    if row is not None:
        return row, True
    return conn.execute("SELECT * FROM jobs WHERE idem_key=%s", (idem_key,)).fetchone(), False


def claim(conn, worker, lease_seconds=LEASE_SECONDS):
    """The oldest ready job whose client isn't busy. For each candidate, in order: the client's advisory lock is taken
    first (another worker claiming for the same client holds it until it commits), then the job row (skipped if another
    worker has it), then a new statement (a fresh snapshot) checks that none of the client's jobs holds a live lease. So
    two workers never run one client's work at once, and other clients' work goes on in parallel."""
    ready = ("(status='queued' AND run_after <= now()) OR (status='running' AND lease_until < now())")
    cands = conn.execute(f"SELECT id, client_id FROM jobs WHERE {ready} ORDER BY id LIMIT 50").fetchall()
    for c in cands:
        if c["client_id"] is not None and not conn.execute("SELECT pg_try_advisory_xact_lock(4207, %s) AS ok", (c["client_id"],)).fetchone()["ok"]:
            continue
        if conn.execute(f"SELECT id FROM jobs WHERE id=%s AND ({ready}) FOR UPDATE SKIP LOCKED", (c["id"],)).fetchone() is None:
            continue
        if c["client_id"] is not None and conn.execute("SELECT 1 FROM jobs WHERE client_id=%s AND id<>%s AND status='running' AND lease_until >= now()",
                                                       (c["client_id"], c["id"])).fetchone():
            continue
        return conn.execute("UPDATE jobs SET status='running', attempts=attempts+1, lease_owner=%s, lease_until=now() + make_interval(secs => %s), "
                            "started_at=COALESCE(started_at, now()) WHERE id=%s RETURNING *", (worker, lease_seconds, c["id"])).fetchone()
    return None


def heartbeat(conn, job_id, worker, lease_seconds=LEASE_SECONDS):
    """Extend the lease. False: this worker doesn't hold it any more."""
    row = conn.execute("UPDATE jobs SET lease_until=now() + make_interval(secs => %s) WHERE id=%s AND lease_owner=%s AND status='running' "
                       "RETURNING id", (lease_seconds, job_id, worker)).fetchone()
    return row is not None


def succeed(conn, job_id, result, worker=None):
    row = conn.execute("UPDATE jobs SET status='succeeded', result=%s, error=NULL, lease_owner=NULL, lease_until=NULL, finished_at=now() "
                       "WHERE id=%s AND status='running'" + (" AND lease_owner=%s" if worker else "") + " RETURNING id",
                       (db.jsonb(result), job_id, *([worker] if worker else []))).fetchone()
    if row is None:
        raise LeaseLost(f"job {job_id}: another worker holds it now; this result isn't recorded")


def fail(conn, job, error, retryable=True, worker=None, retry_after=None):
    guard = " AND status='running'" + (" AND lease_owner=%s" if worker else "")
    extra = [worker] if worker else []
    if retry_after is not None and (job.get("throttles") or 0) < MAX_THROTTLES:
        row = conn.execute("UPDATE jobs SET status='queued', error=%s, lease_owner=NULL, lease_until=NULL, attempts=GREATEST(attempts-1, 0), "
                           "throttles=throttles+1, run_after=now() + make_interval(secs => %s) WHERE id=%s" + guard + " RETURNING id",
                           (error, retry_after, job["id"], *extra)).fetchone()
        return "throttled" if row else "lease_lost"
    if retryable and job["attempts"] < job["max_attempts"] and retry_after is None:
        delay = BACKOFF_SECONDS * (2 ** (job["attempts"] - 1))
        row = conn.execute("UPDATE jobs SET status='queued', error=%s, lease_owner=NULL, lease_until=NULL, "
                           "run_after=now() + make_interval(secs => %s) WHERE id=%s" + guard + " RETURNING id",
                           (error, delay, job["id"], *extra)).fetchone()
        return "queued" if row else "lease_lost"
    if retry_after is not None:
        error = f"{error}\nthrottled {MAX_THROTTLES} times: stopped waiting"
    row = conn.execute("UPDATE jobs SET status='dead', error=%s, lease_owner=NULL, lease_until=NULL, finished_at=now() WHERE id=%s" + guard +
                       " RETURNING id", (error, job["id"], *extra)).fetchone()
    return "dead" if row else "lease_lost"


def worker_name():
    return f"{socket.gethostname()}:{os.getpid()}:{threading.get_ident()}"


class _Heartbeat(threading.Thread):
    def __init__(self, url, job_id, worker, lease_seconds):
        super().__init__(daemon=True)
        self.url, self.job_id, self.worker, self.lease = url, job_id, worker, lease_seconds
        self.stop = threading.Event()
        self.lost = False

    def run(self):
        every = HEARTBEAT_SECONDS or max(1, self.lease // 3)
        while not self.stop.wait(every):
            try:
                with db.session(self.url) as conn:
                    if not heartbeat(conn, self.job_id, self.worker, self.lease):
                        self.lost = True
                        return
            except Exception:                                 # noqa: BLE001  (a missed beat; the next one tries again)
                pass


def run_one(url=None, worker=None, lease_seconds=LEASE_SECONDS):
    """Claim and run one job. Returns the job's final status for this attempt, or None when nothing was ready."""
    worker = worker or worker_name()
    with db.session(url) as conn:
        job = claim(conn, worker, lease_seconds)
    if job is None:
        return None
    if job["attempts"] > job["max_attempts"]:                 # a crashed worker kept failing it: stop here
        with db.session(url) as conn:
            fail(conn, job, (job["error"] or "") + "\nattempts exhausted after the worker stopped mid-job", retryable=False, worker=worker)
        return "dead"
    fn = HANDLERS.get(job["kind"])
    beat = _Heartbeat(url, job["id"], worker, lease_seconds)
    beat.start()
    try:
        if fn is None:
            raise Permanent(f"no handler for job kind {job['kind']!r}")
        with db.session(url) as conn:
            result = fn(conn, job)
            if beat.lost:
                raise LeaseLost(f"job {job['id']}: the lease was lost while it ran")
            succeed(conn, job["id"], result or {}, worker)   # refused (and the handler's writes rolled back) without the lease
        return "succeeded"
    except LeaseLost:
        return "lease_lost"
    except Permanent as e:
        with db.session(url) as conn:
            return fail(conn, job, str(e), retryable=False, worker=worker)
    except Throttled as e:
        with db.session(url) as conn:
            return fail(conn, job, f"throttled: {e}", worker=worker, retry_after=e.retry_after)
    except Exception:                                         # noqa: BLE001  (kept on the job, retried with backoff)
        with db.session(url) as conn:
            return fail(conn, job, traceback.format_exc()[-4000:], worker=worker)
    finally:
        beat.stop.set()


def drain(url=None, limit=50):
    """Run ready jobs until none is left (tests and the seed command)."""
    ran = []
    for _ in range(limit):
        st = run_one(url)
        if st is None:
            break
        ran.append(st)
    return ran


def state(job, busy_clients=()):
    """What a person sees for a job: queued, retrying, throttled, blocked (its client is busy), running, succeeded, dead."""
    s = job["status"]
    if s == "queued":
        if job.get("client_id") in busy_clients:
            return "blocked"
        if (job.get("error") or "").startswith("throttled"):
            return "throttled"
        return "retrying" if job["attempts"] else "queued"
    return s


def listing(conn, firm_id, limit=100):
    rows = conn.execute("SELECT j.id, j.kind, j.status, j.attempts, j.max_attempts, j.throttles, j.error, j.client_id, j.period_id, j.run_after, "
                        "j.created_at, j.started_at, j.finished_at, c.code FROM jobs j LEFT JOIN clients c ON c.id=j.client_id "
                        "WHERE j.firm_id=%s ORDER BY j.id DESC LIMIT %s", (firm_id, limit)).fetchall()
    busy = {r["client_id"] for r in conn.execute("SELECT client_id FROM jobs WHERE firm_id=%s AND status='running' AND lease_until >= now()",
                                                 (firm_id,)).fetchall()}
    return [{**dict(r), "state": state(r, busy), "error": (r["error"] or "").strip().splitlines()[-1][:300] if r["error"] else None} for r in rows]
