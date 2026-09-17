# stack/ran — TASKS (WBS 1.2)

Goal: real radio access. First with srsRAN's **ZMQ virtual radio** (no hardware, no license needed), then `[HW]` on an SDR under a test license or shielded enclosure.

> ⚠️ **Legal, non-negotiable:** transmitting on cellular spectrum without authorization is illegal everywhere. `[HW]` tasks run only inside an RF-shielded enclosure or under a granted test/local license ([docs/spectrum/](../../docs/spectrum/README.md)). Keep this warning in every doc this directory produces. Agents: never mark `[HW]` tasks done without hardware evidence; see [CLAUDE.md](../../CLAUDE.md).

Depends on: `../core/TASKS.md` (1.1-c for 5G, 1.1-d for 4G).

---

## 1.2-a — srsRAN over ZMQ virtual radio (no hardware)

**Steps**
1. Containerize srsRAN Project gNB (pin release) configured for ZMQ device args, attached to the Open5GS AMF; pair with srsUE (also ZMQ) or UERANSIM UE as appropriate. <!-- VERIFY: current srsRAN Project docs for the ZMQ/virtual-radio setup and supported UE pairing -->
2. Same for srsRAN 4G eNB+UE against the EPC path.
3. `verify-zmq.sh` mirroring core's checks (register, IP, local ping) through the srsRAN path.

**Acceptance**
- 5G and 4G ZMQ paths both pass register + local-breakout ping with WAN down.
- Compose/config committed with pins; core's UERANSIM rig still passes (both rigs coexist).

**Status — 5G half: negative finding, not met.** `compose.5g.yaml` +
`verify-5g.sh` exist and were run for real against the live Open5GS AMF;
the gNB does not start at all. Root cause is an upstream packaging bug,
not our config and not amd64 emulation: `gradiant/srsran-5g`'s
entrypoint corrupts its own YAML config whenever `DEVICE_DRIVER=zmq`
(every published tag since 2024, `25_10` included) — full trace in
[README.md "5G ZMQ rig — negative finding"](README.md#5g-zmq-rig-compose5gyaml--negative-finding).
**Upstream fix needed** (not filed as a live issue yet — CLAUDE.md
"never fork upstreams" says report, don't patch): scope
Gradiant/5g-images' `images/srsran-5g/entrypoint.sh` ZMQ awk block to
the `cell_cfg:` section only; today it matches every `tac:` line in the
file, including the one nested in `cu_cp.amf.supported_tracking_areas`,
and duplicates an insertion there that's invalid at that nesting depth.
Separately — and this would still block full acceptance even with that
fix — no ZMQ-capable 5G Standalone UE exists among this project's
approved upstreams (srsRAN Project ships none; UERANSIM has no PHY/ZMQ
layer; Gradiant's public `srsran-4g` UE's 5G mode is EN-DC-only with no
matching NR-carrier eNB published). 4G half: done, see `verify-4g.sh`.
**Follow-up `1.2-a(5G-alt)` — done, acceptance criteria met.** OpenAirInterface
gNB + nrUE over OAI's RF simulator (`rfsimulator`) against the same real
Open5GS 5GC — OAI is an approved upstream alternative (RFC-0001 D1,
`docs/landscape.md`) and ships both halves. Unlike the srsRAN attempt
above, this one actually registers, gets a UE IP, and passes local
breakout, with the primary UERANSIM path re-verified afterward and no
regression. `compose.5g-oai.yaml` + `verify-5g-oai.sh`, run twice from a
clean state, both `ALL CHECKS PASSED`. Full writeup, including two real
problems hit and fixed along the way (a Docker Desktop log-delivery quirk
and a subscriber-resync/PFCP interaction), in
[README.md "5G-alt rig: OpenAirInterface over rfsimulator — positive finding"](README.md#5g-alt-rig-openairinterface-over-rfsimulator-compose5g-oaiyaml-positive-finding).
The 5G ZMQ negative finding above stands as-is — this follow-up doesn't
change srsRAN's status, it satisfies the 5G half of 1.2-a via a different
approved upstream.

## 1.2-b `[HW]` — SIM programming

**Steps**
1. Using `sim-tools` (see [../../sim-tools/TASKS.md](../../sim-tools/TASKS.md)) program a sysmoISIM-class programmable SIM with test PLMN credentials via pySim + a PC/SC reader.

**Acceptance**
- Programmed SIM's IMSI/K/OPc match the subscriber DB entry; values never committed (`.gitignore`).

## 1.2-c `[HW]` — First phone attach (USRP B210)

**Steps**
1. srsRAN + B210, LTE Band and 5G band per the granted license/enclosure setup; start with 4G (broadest handset support), then 5G SA.
2. Attach ≥3 phone models with programmed SIMs; record model, modem, bands, SA support, quirks in `attach-matrix.md`.

**Acceptance**
- One COTS phone browses `library.island` and messages on `chat.island` end-to-end over RF, WAN down.
- `attach-matrix.md` has ≥3 real entries with dates and software versions. Real measurements only.

## 1.2-d `[HW]` — Low-cost radio variant

**Steps**
1. Reproduce 1.2-c on a LimeSDR-class device for the Class C BOM; document stability differences honestly. <!-- VERIFY: current srsRAN support status for LimeSDR/other low-cost SDRs -->

**Acceptance**
- Attach + service use reproduced, or a written finding that the device isn't viable (that's a valid result — record it in node-hw Class C docs).
