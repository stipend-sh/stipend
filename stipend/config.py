"""Agent Commerce Kit — paths, chain constants and configuration.

Design notes that matter:

* The keystore lives OUTSIDE the agent's workspace by default. An agent's
  `read` tool is not reliably confined to its workspace, so a key sitting in
  the workspace is one prompt-injection away from being exfiltrated. Keeping it
  under ~/.config puts it outside the directory the model routinely browses.

* Everything is non-custodial. Keys are generated on this machine, encrypted
  with a passphrase this machine supplies, and never transmitted anywhere. No
  part of this kit can move funds without the local passphrase.
"""

import json
import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

CONFIG_DIR = Path(os.environ.get("STIPEND_HOME", Path.home() / ".config" / "stipend"))
KEYSTORE_FILE = CONFIG_DIR / "keystore.json"
CONFIG_FILE = CONFIG_DIR / "config.json"
LEDGER_FILE = CONFIG_DIR / "spend-ledger.json"
# Every time the limits stopped a payment. The product's central claim is that
# they cannot be talked past; this is the only place that claim leaves evidence.
REFUSALS_FILE = CONFIG_DIR / "refusals.json"

PASSPHRASE_ENV = "STIPEND_PASSPHRASE"

# ---------------------------------------------------------------------------
# Chain — Base mainnet, USDC
# ---------------------------------------------------------------------------

CHAINS = {
    "base": {
        "chain_id": 8453,
        "rpc": "https://mainnet.base.org",
        "usdc": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
        "decimals": 6,
        "explorer": "https://basescan.org/tx/",
    },
    "base-sepolia": {
        "chain_id": 84532,
        "rpc": "https://sepolia.base.org",
        "usdc": "0x036CbD53842c5426634e7929541eC2318f3dCF7e",
        "decimals": 6,
        "explorer": "https://sepolia.basescan.org/tx/",
    },
}

DEFAULT_CONFIG = {
    # Start on testnet. Moving real money should be a deliberate act.
    "chain": "base-sepolia",

    # Spending policy. These are enforced in the signing path, not in the UI,
    # so an agent cannot talk its way past them.
    "max_per_tx_usdc": 25.0,
    "max_per_day_usdc": 100.0,
    "confirm_above_usdc": 10.0,

    # If non-empty, funds may ONLY be sent to these addresses. The single most
    # effective control available: an injected instruction cannot redirect
    # funds to an address that isn't on the list.
    "allowed_destinations": [],

    # First payment to a never-before-paid address requires confirmation,
    # regardless of amount. Blocks drain-by-many-small-payments.
    "confirm_new_destinations": True,

    # Which tier this install is on. Display only — the licence file is
    # what actually decides, and referral commission is a flat 20% for
    # everyone regardless of tier.
    "tier": "free",
}


def ensure_dirs():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(CONFIG_DIR, 0o700)
    except (OSError, NotImplementedError):
        pass  # Windows


def load_config():
    ensure_dirs()
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_FILE.exists():
        try:
            cfg.update(json.loads(CONFIG_FILE.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            pass  # fall back to defaults rather than failing closed on money ops
    return cfg


def save_config(cfg):
    ensure_dirs()
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    try:
        os.chmod(CONFIG_FILE, 0o600)
    except (OSError, NotImplementedError):
        pass


def chain_params(cfg=None):
    cfg = cfg or load_config()
    name = cfg.get("chain", "base-sepolia")
    if name not in CHAINS:
        raise ValueError(f"Unknown chain {name!r}. Known: {', '.join(CHAINS)}")
    params = dict(CHAINS[name])
    params["name"] = name
    if os.environ.get("STIPEND_RPC_URL"):
        params["rpc"] = os.environ["STIPEND_RPC_URL"]
    return params


def to_units(amount_usdc, decimals=6):
    """USDC float -> integer base units, without float drift."""
    from decimal import Decimal, ROUND_DOWN
    q = Decimal(str(amount_usdc)).quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_DOWN)
    return int(q.scaleb(decimals))


def from_units(units, decimals=6):
    from decimal import Decimal
    return float(Decimal(units).scaleb(-decimals))
