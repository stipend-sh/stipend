"""Spending policy — enforced in the signing path, not in the interface.

This exists because the thing holding the key is a language model reading
untrusted text. Moltbook has documented bot-to-bot prompt injection; an agent
that reads a malicious post while holding a spendable key is the obvious
failure mode. Persuasion must not be sufficient to move money.

So the checks live between "decide to send" and "sign", every caller goes
through them, and none of them can be waived by an instruction in the model's
context — only by local configuration the operator controls.
"""

import json
import re
import time
from datetime import datetime, timedelta, timezone

from .config import LEDGER_FILE, REFUSALS_FILE, ensure_dirs, load_config

ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")


class PolicyError(RuntimeError):
    """Raised when a transfer is refused. Never caught internally."""


def validate_address(addr):
    if not isinstance(addr, str) or not ADDRESS_RE.match(addr.strip()):
        raise PolicyError(
            f"Not a valid address: {addr!r}. Expected 0x followed by 40 hex characters."
        )
    return addr.strip()


def _load_ledger():
    if not LEDGER_FILE.exists():
        return {}
    try:
        return json.loads(LEDGER_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        # A corrupt ledger must not silently reset the daily cap to zero spent.
        raise PolicyError(
            f"Spend ledger at {LEDGER_FILE} is unreadable. Refusing to send while "
            "the daily total is unknown. Inspect or delete it deliberately."
        )


def _save_ledger(ledger):
    ensure_dirs()
    LEDGER_FILE.write_text(json.dumps(ledger, indent=2), encoding="utf-8")


def _today():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def spent_today():
    return float(_load_ledger().get(_today(), {}).get("total_usdc", 0.0))


def record_spend(amount_usdc, to_address, tx_hash):
    ledger = _load_ledger()
    day = ledger.setdefault(_today(), {"total_usdc": 0.0, "transfers": []})
    day["total_usdc"] = round(float(day["total_usdc"]) + float(amount_usdc), 6)
    day["transfers"].append({
        "at": datetime.now(timezone.utc).isoformat(),
        "amount_usdc": amount_usdc,
        "to": to_address,
        "tx": tx_hash,
    })
    # Keep 90 days; the ledger is an audit trail, not a database.
    for key in sorted(ledger)[:-90]:
        del ledger[key]
    _save_ledger(ledger)


def settle(approved, tx_reference):
    """Close out a transfer that actually happened: burn the approval, log it.

    Both spending paths — a typed `payout` and an automatic x402 payment — must
    do exactly this, and for a while only one of them did. An approval that
    outlives the payment it was created for is no longer single-use, so this is
    one function rather than two copies that can drift apart again.

    Never raises: the money has already moved and losing the bookkeeping must
    not look like a failed payment.
    """
    if approved.get("approval_token"):
        try:
            from .approvals import consume
            consume(approved["approval_token"])
        except Exception:
            pass    # already consumed, expired, or module unavailable
    record_spend(approved["amount_usdc"], approved["to"], tx_reference)


def confirmation_required(amount_usdc, cfg=None):
    cfg = cfg or load_config()
    return float(amount_usdc) > float(cfg["confirm_above_usdc"])


# How many refusals we keep. A refusal is a few hundred bytes and this file is
# read by a human, not a machine — a thousand is years of history for a normal
# agent and still trivial to load.
MAX_REFUSALS = 1000


def record_refusal(kind, amount_usdc, to_address, message):
    """Write down that the limits stopped something, then let the caller raise.

    The whole product rests on limits that cannot be talked past, and until this
    existed there was no evidence anywhere that they had ever fired. A refusal
    that leaves no trace is indistinguishable from a limit that was never tested.

    Never allowed to interfere with the refusal itself: if writing the file
    fails, the payment is still refused. Recording is bookkeeping, not policy.
    """
    try:
        ensure_dirs()
        try:
            log = json.loads(REFUSALS_FILE.read_text(encoding="utf-8"))
            if not isinstance(log, list):
                log = []
        except Exception:
            log = []

        log.append({
            "at": datetime.now(timezone.utc).isoformat(),
            "kind": kind,
            "amount_usdc": float(amount_usdc) if amount_usdc is not None else None,
            "to": to_address,
            # First line only. The full text is a paragraph of advice aimed at
            # an agent; a human scanning a list wants the reason, not the essay.
            "reason": str(message).splitlines()[0] if str(message) else "",
        })
        if len(log) > MAX_REFUSALS:
            log = log[-MAX_REFUSALS:]
        REFUSALS_FILE.write_text(json.dumps(log, indent=2), encoding="utf-8")
        try:
            REFUSALS_FILE.chmod(0o600)
        except Exception:
            pass
    except Exception:
        pass


def refusals(days=None):
    """Refusals, newest first. Optionally only the last N days."""
    try:
        log = json.loads(REFUSALS_FILE.read_text(encoding="utf-8"))
        if not isinstance(log, list):
            return []
    except Exception:
        return []

    if days:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        log = [r for r in log if (r.get("at") or "") >= cutoff]
    return list(reversed(log))


def _refuse(kind, amount_usdc, to_address, message):
    """Record and raise. One call so no refusal can be added without evidence."""
    record_refusal(kind, amount_usdc, to_address, message)
    raise PolicyError(message)


def check(amount_usdc, to_address, cfg=None, confirmed=False):
    """Authorise a transfer, or raise PolicyError. Call before signing.

    Returns a dict describing the approved transfer.
    """
    cfg = cfg or load_config()
    to_address = validate_address(to_address)

    try:
        amount = float(amount_usdc)
    except (TypeError, ValueError):
        raise PolicyError(f"Amount is not a number: {amount_usdc!r}")

    if amount <= 0:
        raise PolicyError("Amount must be greater than zero.")

    # Destination allowlist — the strongest control here. If it is configured,
    # no amount of persuasion can send funds anywhere else.
    allowed = [a.lower() for a in cfg.get("allowed_destinations") or []]
    if allowed and to_address.lower() not in allowed:
        _refuse("allowlist", amount, to_address,
            f"{to_address} is not in allowed_destinations. Refusing.\n"
            "This list is the reason a compromised or misled agent cannot "
            "redirect your funds. Edit it deliberately with:\n"
            "  stipend config allow-destination 0x..."
        )

    # A one-time approval is the ONLY thing that may exceed a cap, and it is
    # bound to this recipient and this amount. Raising the global cap to afford
    # a single purchase would weaken every future payment to everyone — which is
    # precisely the lever an attacker would reach for.
    approval = None
    try:
        from .approvals import find as _find_approval
        approval = _find_approval(to_address, amount)
    except ImportError:
        approval = None

    per_tx = float(cfg["max_per_tx_usdc"])
    if amount > per_tx and not approval:
        _refuse("over_per_transaction", amount, to_address,
            f"{amount} USDC exceeds max_per_tx_usdc ({per_tx}).\n"
            "Do NOT raise the cap — that weakens every payment to everyone. "
            "Authorise this one payment instead:\n"
            f"  stipend approve --to {to_address} --amount {amount}\n"
            "Single use, this recipient only, expires, and it cannot be redirected."
        )

    # The daily ceiling is NOT overridable by an approval. Otherwise several
    # tricked approvals could be chained to drain the balance in one day.
    per_day = float(cfg["max_per_day_usdc"])
    already = spent_today()
    if already + amount > per_day:
        _refuse("over_daily", amount, to_address,
            f"{amount} USDC would take today's total to {round(already + amount, 6)}, "
            f"over max_per_day_usdc ({per_day}). Already spent today: {already}."
        )

    if confirmation_required(amount, cfg) and not confirmed and not approval:
        _refuse("needs_confirmation", amount, to_address,
            f"{amount} USDC is above confirm_above_usdc "
            f"({cfg['confirm_above_usdc']}) and needs explicit confirmation.\n"
            "Re-run with --confirm. This step exists so that a single "
            "instruction — from anyone, including a web page your agent read — "
            "cannot move a large amount on its own."
        )

    # First payment to an address we have never paid before always needs
    # confirmation, however small.
    #
    # Caps alone do not stop a drain: an attacker only needs many payments that
    # each sit under the confirmation threshold, up to the daily limit, repeated
    # daily. An attacker's address is by definition one you have never paid.
    # Services you already use are unaffected — this fires once, ever, per payee.
    if cfg.get("confirm_new_destinations", True) and not confirmed and not approval:
        try:
            from .ledger import is_new_destination
            if is_new_destination(to_address):
                _refuse("new_destination", amount, to_address,
                    f"{to_address} has never been paid before — first payment to a new "
                    "address needs confirmation, whatever the amount.\n"
                    "Re-run with --confirm if you meant it. This is what stops a drain "
                    "by many small payments that each slip under the limit.\n"
                    "Disable with: stipend config set confirm_new_destinations false"
                )
        except ImportError:
            pass    # ledger unavailable: fall back to the caps above

    return {
        "amount_usdc": amount,
        "to": to_address,
        "approval_token": (approval or {}).get("token"),
        "spent_today_before": already,
        "remaining_today_after": round(per_day - already - amount, 6),
        "confirmed": bool(confirmed),
        "checked_at": time.time(),
    }
