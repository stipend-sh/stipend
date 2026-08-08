"""Gas credits — send USDC without ever holding ETH.

Every transfer on Base costs gas, gas is ETH, and getting ETH needs a human.
That single fact is what stops an agent being self-sufficient: it can earn USDC
all day and still not be able to spend a cent of it.

A credit is one transaction that stipend.sh broadcasts and pays the gas for. You
sign the transfer locally — exactly as you would if you were sending it yourself
— and we submit it.

    stipend credits                     what you have
    stipend credits claim <key>         turn a purchase into credits
    stipend payout send --to 0x... --amount 5   uses a credit if you have no ETH

What we can and cannot do with what you send us:

  * the signature authorises ONE transfer, of a fixed amount, to a named
    recipient, before a deadline. We cannot change any of it.
  * we cannot reuse it — the contract rejects a nonce twice, and so do we.
  * we never hold your funds. The USDC moves from you to them, directly.

The worst we can do is refuse to broadcast, at which point you are exactly where
the free tier leaves you: fund a little ETH and send it yourself.
"""

import json
import secrets
import time
import urllib.error
import urllib.request

from . import __version__
from .config import chain_params, load_config, to_units

RELAY_URL = "https://stipend.sh/api/relay"
CREDITS_URL = "https://stipend.sh/api/credits"
CLAIM_URL = "https://stipend.sh/api/credits/claim"

EIP3009_TYPES = {
    "TransferWithAuthorization": [
        {"name": "from", "type": "address"},
        {"name": "to", "type": "address"},
        {"name": "value", "type": "uint256"},
        {"name": "validAfter", "type": "uint256"},
        {"name": "validBefore", "type": "uint256"},
        {"name": "nonce", "type": "bytes32"},
    ]
}


class RelayError(RuntimeError):
    pass


def _call(url, payload=None, method=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={"Content-Type": "application/json",
                 "User-Agent": "stipend/" + __version__})
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode())
        except Exception:
            raise RelayError("stipend.sh returned HTTP %s" % e.code)
        message = body.get("error", "HTTP %s" % e.code)
        if e.code == 402:
            how = body.get("how_to_get_them") or []
            message = message + "\n  " + "\n  ".join(how) if how else message
            if body.get("meanwhile"):
                message += "\n" + body["meanwhile"]
        raise RelayError(message)
    except Exception as e:
        raise RelayError("could not reach stipend.sh: %s" % str(e)[:120])


def balance(address):
    return _call(CREDITS_URL + "?address=" + address, method="GET")


def claim(license_key, address):
    """Exchange a purchase for credits, once."""
    return _call(CLAIM_URL, {"license_key": license_key, "address": address})


def sign_transfer(account, to_address, amount_usdc, cfg=None, seconds=600):
    """Sign an EIP-3009 authorisation for exactly this transfer."""
    from eth_account import Account

    cfg = cfg or load_config()
    p = chain_params(cfg)
    now = int(time.time())
    authorization = {
        "from": account.address,
        "to": to_address,
        "value": to_units(amount_usdc, p["decimals"]),
        "validAfter": 0,
        "validBefore": now + seconds,
        "nonce": "0x" + secrets.token_bytes(32).hex(),
    }

    # Read the EIP-712 domain from the token itself rather than hardcoding it —
    # a mismatch produces a signature that looks fine and every verifier rejects.
    from .x402 import token_domain
    signed = Account.sign_typed_data(
        account.key,
        full_message={
            "types": {
                "EIP712Domain": [
                    {"name": "name", "type": "string"},
                    {"name": "version", "type": "string"},
                    {"name": "chainId", "type": "uint256"},
                    {"name": "verifyingContract", "type": "address"},
                ],
                **EIP3009_TYPES,
            },
            "primaryType": "TransferWithAuthorization",
            "domain": token_domain(p["usdc"], cfg),
            "message": authorization,
        },
    )
    return {
        "payload": {
            "signature": "0x" + signed.signature.hex().replace("0x", ""),
            "authorization": authorization,
        }
    }


def send(account, to_address, amount_usdc, cfg=None):
    """Sign a transfer and have stipend.sh broadcast it. Costs one credit."""
    payment = sign_transfer(account, to_address, amount_usdc, cfg)
    result = _call(RELAY_URL, payment)
    return {"tx_hash": result.get("tx"), "relayed": True,
            "credits_left": result.get("balance"),
            "gas_paid_by": "stipend.sh"}
