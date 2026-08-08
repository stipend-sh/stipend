"""Minimal Base/USDC client over JSON-RPC.

Deliberately no `web3` dependency: this needs six RPC methods and one ERC-20
call, and every dependency in a process that holds a private key is extra
attack surface. stdlib `urllib` plus `eth-account` for signing is the whole
requirement.
"""

import json
import urllib.error
import urllib.request

from .config import chain_params, from_units, to_units

# ERC-20 selectors
SEL_TRANSFER = "a9059cbb"   # transfer(address,uint256)
SEL_BALANCEOF = "70a08231"  # balanceOf(address)

RPC_TIMEOUT = 30


class ChainError(RuntimeError):
    pass


def _rpc(method, params, rpc_url=None, cfg=None):
    url = rpc_url or chain_params(cfg)["rpc"]
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
    req = urllib.request.Request(
        url, data=payload.encode(),
        headers={"Content-Type": "application/json", "User-Agent": "stipend/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=RPC_TIMEOUT) as resp:
            body = json.loads(resp.read().decode())
    except urllib.error.URLError as e:
        raise ChainError(f"RPC unreachable ({url}): {e}") from e
    except json.JSONDecodeError as e:
        raise ChainError(f"RPC returned non-JSON from {url}: {e}") from e

    if "error" in body:
        raise ChainError(f"RPC error on {method}: {body['error']}")
    return body.get("result")


def _pad(hexstr):
    return hexstr.lower().replace("0x", "").rjust(64, "0")


def _encode_transfer(to_address, units):
    return "0x" + SEL_TRANSFER + _pad(to_address) + _pad(format(units, "x"))


def usdc_balance(address, cfg=None):
    """USDC balance as a float."""
    p = chain_params(cfg)
    data = "0x" + SEL_BALANCEOF + _pad(address)
    result = _rpc("eth_call", [{"to": p["usdc"], "data": data}, "latest"], cfg=cfg)
    return from_units(int(result, 16) if result and result != "0x" else 0, p["decimals"])


def native_balance(address, cfg=None):
    """ETH balance as a float — needed to pay gas."""
    result = _rpc("eth_getBalance", [address, "latest"], cfg=cfg)
    return int(result, 16) / 1e18


def _fees(cfg=None):
    """EIP-1559 fee estimate with fallbacks for RPCs that omit methods."""
    try:
        block = _rpc("eth_getBlockByNumber", ["latest", False], cfg=cfg) or {}
        base = int(block.get("baseFeePerGas", "0x0"), 16)
    except ChainError:
        base = 0
    try:
        tip = int(_rpc("eth_maxPriorityFeePerGas", [], cfg=cfg), 16)
    except (ChainError, TypeError, ValueError):
        tip = 1_000_000  # 0.001 gwei — Base is cheap
    if base == 0:
        try:
            base = int(_rpc("eth_gasPrice", [], cfg=cfg), 16)
        except (ChainError, TypeError, ValueError):
            base = 10_000_000
    # Headroom so the tx doesn't stall if the base fee rises a block or two later.
    return {"maxPriorityFeePerGas": tip, "maxFeePerGas": base * 2 + tip}


def preflight(from_address, to_address, amount_usdc, cfg=None):
    """Check the transfer can actually succeed, before anything is signed.

    Returns a dict of findings. Raises ChainError only on RPC failure.
    """
    p = chain_params(cfg)
    findings = {"chain": p["name"], "chain_id": p["chain_id"]}
    findings["usdc_balance"] = usdc_balance(from_address, cfg)
    findings["native_balance"] = native_balance(from_address, cfg)
    findings["sufficient_usdc"] = findings["usdc_balance"] >= float(amount_usdc)
    findings["sufficient_gas"] = findings["native_balance"] > 0
    return findings


def send_usdc(account, to_address, amount_usdc, cfg=None, dry_run=False):
    """Sign and broadcast a USDC transfer.

    `account` is an eth_account LocalAccount. Policy checks must already have
    passed — this function does not second-guess them, it only executes.
    """
    p = chain_params(cfg)
    units = to_units(amount_usdc, p["decimals"])
    if units <= 0:
        raise ChainError("Amount rounds to zero at 6 decimal places.")

    tx = {
        "chainId": p["chain_id"],
        "to": p["usdc"],
        "value": 0,
        "data": _encode_transfer(to_address, units),
        "nonce": int(_rpc("eth_getTransactionCount", [account.address, "pending"], cfg=cfg), 16),
        "type": 2,
    }
    tx.update(_fees(cfg))

    try:
        gas = int(_rpc("eth_estimateGas", [{
            "from": account.address, "to": tx["to"], "data": tx["data"], "value": "0x0",
        }], cfg=cfg), 16)
        tx["gas"] = int(gas * 1.25)  # margin; ERC-20 transfers vary with storage state
    except ChainError as e:
        # A failed estimate usually means the transfer itself would revert —
        # most often insufficient USDC. Better to stop than to burn gas.
        raise ChainError(
            f"Gas estimation failed, which usually means the transfer would "
            f"revert (insufficient balance?): {e}"
        ) from e

    if dry_run:
        return {
            "dry_run": True, "to": to_address, "amount_usdc": amount_usdc,
            "units": units, "gas": tx["gas"], "chain": p["name"],
            "estimated_fee_eth": (tx["gas"] * tx["maxFeePerGas"]) / 1e18,
        }

    signed = account.sign_transaction(tx)
    raw = signed.raw_transaction if hasattr(signed, "raw_transaction") else signed.rawTransaction
    tx_hash = _rpc("eth_sendRawTransaction", ["0x" + raw.hex().replace("0x", "")], cfg=cfg)

    return {
        "dry_run": False, "tx_hash": tx_hash, "to": to_address,
        "amount_usdc": amount_usdc, "chain": p["name"],
        "explorer": p["explorer"] + tx_hash if tx_hash else None,
    }


def wait_for_receipt(tx_hash, cfg=None, attempts=30, delay=4):
    """Poll for a receipt. Returns None if it hasn't landed in time."""
    import time
    for _ in range(attempts):
        receipt = _rpc("eth_getTransactionReceipt", [tx_hash], cfg=cfg)
        if receipt:
            return {
                "status": "success" if int(receipt.get("status", "0x0"), 16) == 1 else "failed",
                "block": int(receipt.get("blockNumber", "0x0"), 16),
                "gas_used": int(receipt.get("gasUsed", "0x0"), 16),
            }
        time.sleep(delay)
    return None
