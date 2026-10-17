"""Who is acting, and what their role lets them do.

Locally the product has no login page (owner, 2026-10-07): every request from this Mac acts as the firm's owner. The
identity model is already the one external access needs: users belong to a firm, have a role, and every permission is
checked here and every query is scoped by the user's firm (product/service.py). Managed sign-in with MFA plugs in by
resolving the Identity from a verified session instead of the local owner (docs/74, B-11)."""
from dataclasses import dataclass

from . import config
from .errors import Forbidden

ROLES = ("owner", "reviewer", "preparer", "client_viewer", "agent")   # agent: the preparer agent (product/preparer.py)

# client_viewer is the future client portal's role: it never sees the firm's internal workspace.
PERMISSIONS = {
    "view_workspace": {"owner", "reviewer", "preparer", "agent"},
    "manage_clients": {"owner"},
    "record_authorization": {"owner"},
    "upload": {"owner", "reviewer", "preparer", "agent"},
    "run_engine": {"owner", "reviewer", "preparer", "agent"},
    "approve_setup": {"owner", "reviewer"},
    "decide_change_set": {"owner", "reviewer"},           # an approval names the exact change set (its hash)
    "decide_exception": {"owner", "reviewer"},
    "record_time": {"owner", "reviewer", "preparer"},
    "build_package": {"owner", "reviewer", "preparer"},
    "lock_period": {"owner", "reviewer"},                # an administrative freeze, not a release
    "unlock_period": {"owner"},
    "confirm_facts": {"owner", "reviewer"},               # basis, entity type, fiscal year end, policies (product/facts.py)
    "reopen_period": {"owner"},                           # a released month, with a reason (product/authority.py)
    "recover_operations": {"owner"},
    "accept_unreconciled": {"owner"},                     # an account with no statement, released without a reconciliation
    "manage_engagement": {"owner"},                       # the client's engagement: services, responsibilities, approvers
    "approve_schedule": {"owner", "reviewer"},            # a schedule a person proposed (never by the person who proposed it)
    "record_tax_adjustment": {"owner", "reviewer", "preparer"},
    "approve_tax_adjustment": {"owner", "reviewer"},
    "manage_retention": {"owner"},
    "approve_mapping": {"owner", "reviewer"},             # how a table's columns are read, for the client's files (product/mappings.py)
}


@dataclass(frozen=True)
class Identity:
    user_id: int
    firm_id: int
    role: str
    email: str
    name: str


def can(identity: Identity, permission: str) -> bool:
    return identity.role in PERMISSIONS[permission]


def require(identity: Identity, permission: str):
    if not can(identity, permission):
        raise Forbidden(f"your role ({identity.role}) can't {permission.replace('_', ' ')}")


def resolve(conn, dev_user_email=None) -> Identity:
    """The acting user: the X-Dev-User header's user when developer auth is on (tests only), otherwise the local owner."""
    email = dev_user_email if (config.DEV_AUTH and dev_user_email) else config.LOCAL_OWNER_EMAIL
    row = conn.execute("SELECT id, firm_id, role, email, name FROM users WHERE email=%s", (email,)).fetchone()
    if row is None:
        raise Forbidden("no such user")
    return Identity(row["id"], row["firm_id"], row["role"], row["email"], row["name"])
