# Drills

A network first switched on during a disaster will not work. Drills are how an association finds that out in peacetime instead. This page describes the drills the project ships a script for; the activation exercise itself (the flow chart in [README.md](README.md) §4) is the frame every drill runs inside.

Every drill ends with a **timed log**, a short drill report, and issues filed for whatever did not go as expected. A drill where everything went as expected and nothing was written down did not happen.

## Drill 1 — Unplug test (single island)

**What it proves:** the island works with every backhaul down: phones attach, the portal, library, chat and voice answer, DNS resolves `.island` names. The script is [`stack/backhaul/unplug-test.sh`](../stack/backhaul/unplug-test.sh); the operator-facing description is in [docs/deployment-model.md](../docs/deployment-model.md).

## Drill 2 — Partition drill (two islands, roaming)

**What it proves:** what happens to a *visitor* — a subscriber of a partner island who is attached to yours — when the link between the two islands goes down, and what your operators do about it. This is the scripted form of WBS 4.1; the mechanism it exercises is decided in [RFC-0003](../rfcs/rfc-0003-roaming.md) D1 and D3.

The five things it checks, in order, and what "as expected" means for each:

| Step | What the script does | Expected, and why |
|---|---|---|
| (a) | A visitor from the partner island attaches to your island. | Registers, gets an address from **your** pool, reaches your services. Authentication was answered by their *home* island over the inter-island link; their key never came to you. |
| (b) | The inter-island link is cut while the visitor is attached. | **The visitor keeps working.** Their session is anchored on your island's own core; nothing about a live session needs the home island. The core only re-contacts home when a phone has no valid security context (Open5GS AMF, `src/amf/gmm-sm.c`, `SECURITY_CONTEXT_IS_VALID`). |
| (c) | With the link still cut, the visitor's phone re-registers from scratch (power cycle, airplane mode, out of coverage and back). | **Registration is refused.** You hold no key for the visitor, only their session policy, so a fresh authentication needs their home island and it is unreachable. This is the honest limit of roaming during a partition; nothing in the design pretends otherwise. |
| (d) | Your SIM table issues the visitor a **guest identity**: a normal local subscriber in your own block, provisioned with `resccom-sim`, with no involvement of the home island. | The guest registers and reaches your services with the link still down. This is the fallback for anyone you cannot authenticate: cache exhausted, home island unknown, or no ResCCOM SIM at all. |
| (e) | The link is restored; the visitor's original identity registers again. | Registers via their home island as before; the home island's own log shows both the first and the second visit. The script prints how long the link took to come back and how long until the visitor was registered again. |

### Running it

The drill runs entirely in software on one Docker host — two full islands as containers, an OpenAirInterface simulated phone, a simulated inter-island link. No radio is involved and nothing is transmitted.

```sh
cd stack/federation
./two-island.sh --log-level debug drill --ue oai
```

It takes about ten minutes. It prints the evidence for every step as it goes (ping results, the refusal line from your island's AMF in step (c), the guest attach, the recovery times), then a summary with one line per step reading `AS EXPECTED` or `DIFFERENT FROM EXPECTED`, and tears both islands down. If your own island's core was already running before the drill, it is left exactly as it was.

The measured values from the project's own runs are in [docs/poc-writeup.md](../docs/poc-writeup.md) ("Partition drill"). Record yours the same way: whether the live session survived, and the two recovery times from step (e).

### What it means for your subscribers

Tell visitors plainly, before a crisis: **while the link to your home island is up, you attach here as you would at home. If your phone reconnects while that link is down, it cannot get on until the link returns — come to the SIM table and we will issue you a guest SIM on this island.** A guest identity is a new local subscriber, not a copy of the visitor's home identity; when the link returns, their own SIM works again and the guest one can be revoked.

### What this drill does not cover

- **Messaging across islands during a partition.** Matrix federation between islands is not enabled in the shipped configuration (the Synapse homeserver has no federation listener and an empty federation whitelist, and the inter-island link carries only the roaming signalling ports). A cross-island chat room, and what happens to its messages during a partition, is a separate task noted in [stack/federation/TASKS.md](../stack/federation/TASKS.md) 4.1.
- **Real radios, real phones, a real WAN.** Everything above is `[SIM]`. A real phone's own behaviour on losing and regaining registration, and a real satellite or fibre link's failure modes, are what a partner lab repeats over the air ([docs/partner-labs.md](../docs/partner-labs.md)).
- **4G roaming.** The drill runs the 5G path only; 4G inter-island roaming (WBS 3.3-d) is not yet proven at all.
