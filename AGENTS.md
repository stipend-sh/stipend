# AGENTS.md

Notes for an agent working on this repository. Read this before changing code.

## What this is

`stipend` is a non-custodial USDC wallet on Base that an AI agent installs
without a human. The key is generated on the machine that runs it and never
leaves. Spending limits are enforced in the signing path.

Python only. One runtime dependency: `eth-account`.

## Run it

    pip install -r requirements.txt
    python -m stipend --help
    python -m stipend mcp          # MCP server, JSON-RPC over stdio

Docker, for registries that introspect the MCP server:

    docker build -t stipend .
    docker run -i --rm stipend

## The rule that matters

**Limits are enforced between deciding and signing, in code the model cannot
reach.** `policy.check()` runs before any signature exists. If you find yourself
moving a check after `sign_transfer`, or making a limit configurable by anything
that arrives over the network, stop — that is the product, not an
implementation detail.

Specifically, do not:

- widen a cap, add a bypass flag, or make a limit readable-and-writable by a
  tool exposed over MCP
- move key material anywhere other than the local keystore
- add a hosted mode for the MCP server; a hosted wallet server would put the
  key on someone else's machine and make this custodial
- weaken `locks.payment_lock()` — it is what stops two concurrent sends from
  both passing the same daily cap

## Where the money paths are

    policy.py      the caps, the allowlist, the confirmation rules
    approvals.py   one-shot approval tokens, matched exactly, never by ceiling
    locks.py       OS-level exclusive lock around the whole send
    relay.py       signing, broadcast, and the durable pending record
    ledger.py      what happened, and destination trust state
    mcp.py         the tool surface; deliberately exposes no config writes

Anything touching those four files is a money path. Treat a change there as
requiring proof it still refuses what it refused before.

## Honesty rules for docs and listings

Claims in this repo, on the site, and in any directory listing must be true of
the code as shipped, not of the intent. The project is **not audited** and says
so. Do not add "audited", "certified", "the first", "the only", or any user,
install or volume number.

## Tests

    python -m stipend selftest

If you change a limit, add the case that proves the old behaviour is gone and
the neighbouring refusals still hold.
