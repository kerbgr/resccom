# Security

## Reporting a vulnerability

Until a dedicated address exists, open a GitHub security advisory (private) on this repo. Do not open public issues for exploitable problems. <!-- VERIFY: replace with security@ address once org email exists -->

## Threat model (WBS 3.1 — summary; full model: [docs/threat-model.md](docs/threat-model.md), draft, external review pending)

**Adversaries in scope:** opportunistic attackers on the local network; criminals exploiting a crisis (fraud, impersonation of coordinators); vandalism/theft of nodes; an infrastructure attacker degrading backhauls (cable cuts, satellite denial, jamming).

**Explicit non-goals — we never claim to provide:**

- **Covertness.** A radiating cellular network is detectable, direction-findable, and jammable by anyone with modest equipment. ResCCOM is resilience infrastructure operated lawfully and openly by local associations — not a tool for hiding from a state.
- **Protection of RF metadata.** Who is attached to which cell, and when, is visible at the radio layer to a capable observer.
- **Anonymity.** Local operators can see subscriber activity to the same degree any network operator can.

**What we do provide (and must not silently regress):**

- E2E-encrypted messaging by default (Matrix E2EE).
- Standard 3GPP air-interface encryption and mutual authentication (SIM credentials held only by the local association).
- Per-deployment PKI; no central ResCCOM service ever holds subscriber keys.
- Signed node images and updates (Phase 3, WBS 3.4).
- Honest UI copy: the node landing page states plainly what is and is not protected.

## Rules for contributors and agents

- No real Ki/OPc values, IMSIs, or private keys in the repo — test vectors only, in `*.example.*` files.
- Any copy (docs, portal, launch material) that implies covertness or state-level protection is a bug; fix it as such.

## Dual-use notice (for humans and AI-assisted contributors)

This project is dual-use by nature: private cellular infrastructure, subscriber-credential handling, host-level network control. The same knowledge that keeps a village connected in a crisis could serve unlawful ends elsewhere. Consequences we accept:

- **Every capability here is scoped to lawful, openly operated, association-owned networks** (RFC-0001 D7/D8). Contributions that push toward covert operation, evading regulators, interfering with public networks, or extracting real subscriber credentials are out of scope and will be declined regardless of stated intent.
- **AI coding assistants may hit safety guardrails on this material** — refusals, warnings, or automatic model reassignment mid-session have been observed during development (2026-09-13, during a routine review of the SIM-provisioning tooling). Treat that as a signal, never an obstacle: **never rephrase, split, or otherwise work around a guardrail.** Stop, check the task is within the scope above, and if it is, finish it under human review. A guardrail firing is not evidence of a flaw in this project, but it is a reminder of what this project touches.
- Work completed under any model is held to the same bar: acceptance criteria re-run by a human or reviewing agent before it is trusted (see [CONTRIBUTING.md](CONTRIBUTING.md)).

## Lab-profile register — weaknesses that must never reach a deployment

The current stack is the **lab profile** (CLAUDE.md conventions): built to prove the architecture on one developer machine, not to protect anyone. Each item below is deliberate and documented where it lives; this register exists so nobody deploys the lab profile to real people by accident. **`island-init` (RFC-0005) must close every row before a production profile exists**, and the full threat model (WBS 3.1) must revisit each.

| Lab-profile weakness | Where | Why acceptable in the lab only |
|---|---|---|
| Test PLMN `001/01` and public UERANSIM test K/OPc vectors | stack/core, stack/ran, sim-tools `--test` | Published vectors; any phone with them attaches. Production islands get registry-allocated PLMN/IMSI blocks and per-association keys. |
| `island.sh up` uses a hardcoded dev store passphrase (`dev-only-ephemeral`) and a throwaway subscriber store | island.sh | Convenience for the one-command demo; real subscriber stores are association-held with a real passphrase, never scripted. |
| Open self-registration on `chat.island`; unauthenticated `talk.island` | stack/services | No WAN path to abuse from in the lab; unacceptable the moment an island has any uplink or untrusted users. |
| Self-signed TLS on `talk.island`/`chat.island`; no per-deployment PKI yet | stack/services | Needed for browser WebRTC to function; not a trust property. Real PKI is WBS 3.4. |
| `services_net` not `internal`; UEs reach WAN when an uplink exists | stack/core, stack/backhaul | Backhaul semantics are 1.4's; production QoS/egress policy per island is undefined until the threat model. |
| Portal shows placeholders for association name/operator contact | stack/services portal | Must be real before any human relies on it. |
| Unplug/QoS tests run privileged containers that edit host firewall state | stack/backhaul | Test tooling for developers; never part of a deployed node's runtime. |
| `two-island.sh`/`two_island_setup.py` hardcode each island's WireGuard peer endpoint as a static address on a simulated WAN bridge (`stack/federation/compose.wan.yaml`, `10.200.0.0/24`, replacing an earlier `host.docker.internal` mapping — WBS 3.3-c v2f, fixed a Docker Desktop NAT-hairpin fault that black-holed the overlay) | stack/federation | Test harness only, for running two islands on one Docker host; the transient peered `island.yaml` copies it writes are never committed. A real deployment's `federation.peers[]` endpoint comes from the registry allocation (RFC-0005) over a real routable address, never this value. |
| No signed images/updates; images pulled by tag pin only | all | WBS 3.4. |
| `console.island` (Island Console) uses one shared, per-boot operator token (no per-operator identity, no HTTPS in front of it) for write access, reachable by anyone on `services_net` | stack/services/config/console | 2.1-f removed the private signing key, the read-write repo mount, and the Docker socket from this container entirely (signing/render/restart now happen host-side via `island.sh apply`, RFC-0006 D5) and added the token gate on every write endpoint — but the token is still a single shared secret printed to a terminal, not a real per-operator credential with revocation or audit-by-identity. RFC-0006 D5's association-held auth is still the WBS 3.4 hook this row exists to track. |
| `resccom-sim roaming export`/`import`'s policy-only file hand-over between islands is unsigned and unencrypted plaintext JSON — `two-island.sh roam` just copies it on disk between the two checkouts it manages (WBS 3.3-c v2h) | sim-tools, stack/federation | The record itself carries no credential (K/OPc/AMF are a hard refuse on import, enforced in code — see sim-tools/README.md "Inbound roaming"), so a tampered or intercepted file can misstate policy (e.g. an IMSI, `lbo_roaming_allowed`) but cannot leak or forge a subscriber's key material. A real association-to-association exchange needs the file signed by the home island and the import verified against the sender's known key, the same ceremony `island.yaml`/RFC-0005 already uses for identity — that's WBS 3.4 (PKI), not built here. |

Adding a new lab-only shortcut? Add a row here in the same commit.
