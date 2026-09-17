# stack/core — TASKS (WBS 1.1)

Goal: Open5GS dual-mode core running under Docker Compose on Debian 12+/Ubuntu LTS, verified end-to-end with UERANSIM. No radio hardware involved.

Conventions (from [CLAUDE.md](../../CLAUDE.md)): test PLMN `001/01`, TAC `1`, UE subnet `10.45.0.0/16`, services subnet `10.46.0.0/24`. Pin every image tag and record pins in `README.md` under "Versions".

---

## 1.1-a — Compose file for Open5GS 5G SA core

**Steps**
1. Research current stable Open5GS release and a maintained container image or build path. <!-- VERIFY: check open5gs.org and its GitHub for the current release; prefer official images if published, else build from the pinned release tag -->
2. Write `compose.yaml` bringing up: NRF, AMF, SMF, UPF, AUSF, UDM, UDR, PCF, NSSF, BSF + MongoDB. AMF NGAP exposed on the host; UPF with `10.45.0.0/16` TUN.
3. Config files in `config/`, templated only where our conventions differ from upstream defaults (PLMN, TAC, subnets, DNS pointing at `10.46.0.53`).
4. Write `README.md`: prerequisites, exact bring-up commands, "Versions" section with every pin.

**Acceptance**
- `docker compose up -d` on a clean Debian/Ubuntu host → all containers healthy after 60 s.
- `docker compose logs amf | grep -i ngap` shows the AMF listening.
- Config contains no real credentials; anything secret-shaped is `*.example.*`.

## 1.1-b — Subscriber management (manual path)

**Steps**
1. Document adding a test subscriber (IMSI `001010000000001`, test K/OPc vectors from UERANSIM's docs) via Open5GS's WebUI or `open5gs-dbctl`.
2. Store the test subscriber set in `subscribers.example.json` with a loader script `load-subscribers.py` (idempotent).

**Acceptance**
- Running the loader twice results in exactly one subscriber record.
- `README.md` shows the manual path and the scripted path.

## 1.1-c — UERANSIM verification rig

**Steps**
1. Add `compose.sim.yaml` overlay: UERANSIM gNB + one UE container, configured for PLMN `001/01` against the AMF. <!-- VERIFY: current UERANSIM release/tag -->
2. Write `verify.sh`: brings up core + sim, waits, then runs the checks below, exits non-zero on any failure.

**Acceptance (this is the M1-core gate)**
- UE registers: UERANSIM logs show `Registration is successful` (or current upstream equivalent — quote the actual line in README).
- UE gets an IP in `10.45.0.0/16`.
- `ping -I <ue-tun> 10.46.0.1` succeeds from inside the UE container (local breakout works).
- With the host's default route removed (or WAN interface down), registration and local ping still succeed — offline-first proof.

## 1.1-d — EPC (4G) mode

**Steps**
1. Extend compose with Open5GS EPC components (MME, SGW-C/U, PGW via SMF/UPF in 4G mode, HSS — and PCRF: SMF refuses a 4G CreateSession without a Gx Diameter peer) or dual-mode config per current upstream guidance.
2. Verify with srsRAN 4G ZMQ UE+eNB (see `../ran/TASKS.md` 1.2-a) or an LTE-capable simulator.

**Acceptance**
- A simulated 4G UE attaches and pings `10.46.0.1` while the 5G path of 1.1-c still passes.

## 1.1-e — Teardown & state hygiene

**Acceptance**
- `docker compose down -v` then `up -d` + loader → clean, working state; documented in README.
- MongoDB data dir is in `.gitignore` and never committed.
