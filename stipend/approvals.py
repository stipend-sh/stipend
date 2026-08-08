"""One-time payment approvals.

The problem this solves: raising `max_per_tx_usdc` to afford one purchase
weakens the limit for *every* payment, to *anyone*, permanently. An attacker who
can talk an agent into raising its cap then has a raised cap to work with.

So don't raise the cap. Authorise one payment instead:

    stipend approve --to 0xSELLER --amount 39

That authorisation is bound to a single recipient, a single amount, expires, and
is consumed on use. It cannot be pointed somewhere else, cannot be reused, and
leaves the global limits untouched.

Approvals are the only thing that can exceed a cap, and they are deliberately
narrow: an attacker who obtains one can spend exactly that amount, exactly once,
to exactly the address the user already chose to pay.
"""

import json
import os
import secrets
from datetime import datetime, timedelta, timezone

from .config import CONFIG_DIR, ensure_dirs

APPROVALS_FILE = CONFIG_DIR / "approvals.json"
DEFAULT_TTL_MINUTES = 30


class ApprovalError(RuntimeError):
    pass


def _load():
    if not APPROVALS_FILE.exists():
        return {}
    try:
        return json.loads(APPROVALS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        # Fail closed: an unreadable store means no approvals exist, so
        # everything falls back to the ordinary caps.
        return {}


def _save(data):
    ensure_dirs()
    APPROVALS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    try:
        os.chmod(APPROVALS_FILE, 0o600)
    except (OSError, NotImplementedError):
        pass


def _prune(data):
    now = datetime.now(timezone.utc)
    live = {}
    for token, a in data.items():
        if a.get("used"):
            continue
        try:
            if datetime.fromisoformat(a["expires_at"]) > now:
                live[token] = a
        except (KeyError, ValueError):
            continue
    return live


def create(to_address, amount_usdc, ttl_minutes=DEFAULT_TTL_MINUTES, note=None):
    """Authorise exactly one payment. Returns the approval record."""
    from .policy import validate_address
    to_address = validate_address(to_address)

    try:
        amount = float(amount_usdc)
    except (TypeError, ValueError):
        raise ApprovalError(f"Amount is not a number: {amount_usdc!r}")
    if amount <= 0:
        raise ApprovalError("Amount must be greater than zero.")

    ttl = max(1, min(int(ttl_minutes), 24 * 60))
    now = datetime.now(timezone.utc)
    token = secrets.token_hex(8)

    data = _prune(_load())
    data[token] = {
        "to": to_address,
        "amount_usdc": amount,
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(minutes=ttl)).isoformat(),
        "note": note,
        "used": False,
    }
    _save(data)
    return {"token": token, **data[token]}


def find(to_address, amount_usdc):
    """An unused, unexpired approval matching this exact payment, or None.

    Matching is strict: same recipient, and an amount at least as large as the
    payment. A $39 approval cannot be stretched to $40, and cannot be redirected.
    """
    data = _prune(_load())
    for token, a in data.items():
        if a["to"].lower() != str(to_address).lower():
            continue
        if float(amount_usdc) <= float(a["amount_usdc"]) + 1e-9:
            return {"token": token, **a}
    return None


def consume(token):
    """Mark an approval used. Called only after a payment actually succeeds."""
    data = _load()
    if token not in data:
        raise ApprovalError("Approval no longer exists.")
    data[token]["used"] = True
    data[token]["used_at"] = datetime.now(timezone.utc).isoformat()
    _save(_prune(data))
    return True


def active():
    data = _prune(_load())
    _save(data)
    return [{"token": t, **a} for t, a in data.items()]


def revoke(token=None):
    """Cancel one approval, or all of them."""
    data = _load()
    if token is None:
        _save({})
        return len(data)
    if token not in data:
        raise ApprovalError(f"No approval with token {token}.")
    del data[token]
    _save(data)
    return 1
