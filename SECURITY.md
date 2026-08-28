# Security

This is a wallet. It holds real money on Base, and the code that decides
whether a payment happens runs on the user's own machine. If you find something
wrong with it, we would rather hear it from you than from an incident.

## Reporting

Email **support@stipend.sh**. No form, no account, no platform in between.

Tell us what you found and how you verified it. If it needs a proof of concept,
send the exact request. We will confirm within a couple of days and tell you
what we are doing about it, including when we think you are wrong and why.

We do not run a paid bounty. We can credit you here, under whatever name you
choose, and we will say plainly what you found.

## What we will do

- Reply, in words, not a ticket number.
- Fix what is real, and tell you when it is live so you can re-check it.
- Say so when a finding does not reproduce, and show you what we tested. If you
  can then reproduce it, that is a finding and we will treat it as one.

## What is in scope

- `stipend.sh` and its API — `/api/*`
- The published client: `https://stipend.sh/stipend.tar.gz`, and the
  `stipend` package on npm
- The MCP server that ships with it

## What is not

- The keystore format. It is the same encrypted format geth and MetaMask use;
  breaking scrypt is not a stipend finding.
- Anything requiring the user's passphrase or physical access to their machine.
- Volumetric denial of service. Tell us if you find an amplification, but do
  not run one.

Please do not use another person's wallet or address to demonstrate anything.
Use your own, or one of the burn addresses.

## Acknowledgments

**jackbone** — August 2026. A full audit of the API, re-verified before
reporting and delivered with the parts that were sound listed alongside the
parts that were not. Found that the welcome grant accepted any USDC balance at
all: an address holding one millionth of a dollar of somebody else's stray
change qualified for three relayed transactions at our expense. Also found an
unauthenticated, unrate-limited balance read, credit data returned on relay
paths that ran before the signature was checked, capability flags on the health
endpoint, and raw EVM reverts echoed to the caller. Six findings, all fixed.
