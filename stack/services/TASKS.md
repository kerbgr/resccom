# stack/services — TASKS (WBS 1.3)

Goal: the island's service layer — NOMAD (knowledge), Matrix (messaging), Jitsi (voice/video), local DNS, and a landing page — reachable from the UE subnet with **all backhauls down**. Services live on `10.46.0.0/24`; DNS zone `.island`.

Depends on: `../core/TASKS.md` 1.1-c passing (you need a simulated UE to verify from).

---

## 1.3-a — Local DNS + zone

**Steps**
1. Deploy a small authoritative DNS container (CoreDNS or dnsmasq) at `10.46.0.53`, authoritative for `.island`: `portal.island`, `library.island`, `learn.island`, `maps.island`, `chat.island`, `talk.island`.
2. Wire the core's PDU-session DNS option to `10.46.0.53` (touchpoint in `../core/config/`).
3. Upstream resolution: forward to WAN resolvers *when available*, SERVFAIL cleanly when not — never hang.

**Acceptance**
- From the UERANSIM UE container: `dig +short portal.island @10.46.0.53` returns `10.46.0.x` with the host's WAN down.

## 1.3-b — NOMAD as a component

**Steps**
1. Deploy Project NOMAD per its own docs, unmodified, on the services network. <!-- VERIFY: NOMAD's current install method (it manages its own Docker services via Command Center) — document how it coexists with our compose; do not fork it -->
2. Preload one small Kiwix ZIM (e.g. Wikipedia top-100) so the demo has real content; document how associations choose/load full libraries.
3. Map `library.island` / `learn.island` / `maps.island` to the NOMAD services.

**Acceptance**
- From the UE container, `curl -s http://library.island` returns Kiwix content, WAN down.
- NOMAD upstream is version-pinned and unmodified; our glue is only networking + DNS.

## 1.3-c — Matrix + Element

**Steps**
1. Deploy a Matrix homeserver (evaluate Synapse vs Dendrite for a constrained node; record the choice and why in README) with server name `chat.island`, E2EE default on. <!-- VERIFY: current upstream recommendation for small homeservers -->
2. Element Web at `chat.island`; registration flow suitable for offline use (local registration, no email verification).
3. Federation config prepared but disabled (Phase 4 turns it on between islands).

**Acceptance**
- Two accounts created from the UE subnet exchange E2EE messages, WAN down.

## 1.3-d — Jitsi voice/video

**Steps**
1. Jitsi Meet at `talk.island`, STUN/TURN scoped to local subnets.

**Acceptance**
- Two browser clients on the UE subnet hold an audio call, WAN down. (Video quality noted, not gated — sim-network bandwidth isn't representative.)

## 1.3-e — Landing page / captive portal

**Steps**
1. Static page at `portal.island` (and as the resolve-anything fallback when WAN is down): what this network is, what works right now (live status of services + backhaul state), what is/isn't protected (**copy constraints in [SECURITY.md](../../SECURITY.md) — no covertness claims**), and how to reach the local operators.
2. Status comes from a tiny endpoint checking service health + WAN reachability; no external assets, must render on a 5-year-old Android browser.

**Acceptance**
- `curl http://portal.island` from the UE shows correct live status with WAN both up and down.

## 1.3-f — One-command island

**Steps**
1. Top-level `island.sh up|down|status` (or Make targets) driving core + services compose files in the right order.

**Acceptance (M1-sim gate, with core 1.1-c)**
- Fresh Debian host, WAN disconnected after image pulls: `island.sh up` → UERANSIM UE registers, browses `library.island`, sends an E2EE Matrix message. Documented start-to-finish in `README.md` — this doc is what an outside contributor must be able to follow cold.
