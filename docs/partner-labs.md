# Run an island: an invitation to university labs

ResCCOM is looking for university labs with 4G/5G test capability — an SDR, a shielded box or a test/local licence, and a student or two — to each run **one island** and take it to TRL 4 with real radio, then **federate it with another lab's island** over the internet. Several independently run islands are the experiment this project exists for; one lab alone cannot produce it.

The project is open source (Apache-2.0 glue, unmodified upstream components), owned by no company, and intended to end up under community or NGO stewardship ([GOVERNANCE.md](../GOVERNANCE.md)). Its purpose is stated in the [README](../README.md): keep a community able to talk, find what it needs, and reach help when infrastructure fails — in crises, and in places that never had reliable infrastructure.

## What you get on day one (no hardware)

The complete island runs in software on one Linux/macOS machine and verifies itself end to end in about three minutes: [QUICKSTART.md](../QUICKSTART.md). That is the reproduction we ask every lab to do first — and to file a [reproduction report](https://github.com/kerbgr/resccom/issues/new?template=repro-report.yml) whether it passed or failed. A failed report from a stranger is the most valuable thing this project can receive.

## What a TRL-4 island means here

| Stage | What you do | What it proves | Where it's specified |
|---|---|---|---|
| 0 | Reproduce the simulated island on your own machine. The baseline is **CI green on Linux**: the same verify script passes on a plain x86 runner on every push ([ci.yml](../.github/workflows/ci.yml)), so a failure on your machine is diffed against a known-green run, not against the maintainer's laptop | The docs are sufficient (milestone M2) | [QUICKSTART.md](../QUICKSTART.md) |
| 1 | Program test SIMs, attach real phones to the island over an SDR **inside a shielded enclosure or under your licence** | Real radio access; the attach matrix per handset | [stack/ran/TASKS.md](../stack/ran/TASKS.md) 1.2-b/c/d |
| 2 | Measure: setup time, coverage in your enclosure/site, power draw of the node | Numbers that replace design targets in the BOMs | [node-hw/](../node-hw/README.md) |
| 3 | Federate with another lab's island across the internet (WireGuard overlay, allow-listed), then run the partition drill | Roaming without key sharing; behaviour when the link dies (milestone M3) | [stack/federation/TASKS.md](../stack/federation/TASKS.md), [RFC-0003](../rfcs/rfc-0003-roaming.md) |
| 4 | Run the island as a *service* for a day with your students as users: library, chat, voice, the browser emergency portal, with WAN unplugged | The island-native emergency service under real people ([RFC-0004](../rfcs/rfc-0004-emergency-interop.md)) | [playbook/](../playbook/README.md) drills |

Every stage has acceptance criteria in a `TASKS.md`; "done" is a passing verify script and a row in [STATUS.md](../STATUS.md), never a claim.

## What a lab needs

- **Compute:** any x86 Linux box (an Intel N100 mini-PC is the reference; Apple-Silicon Macs work for the simulated island under emulation).
- **Radio:** a USRP B210 or similar for the reference path; a LimeSDR-class device if you want to help validate the low-cost backpack node. Both lanes are open.
- **Legal:** a test/experimental licence from your regulator, a local-licence band where your country offers one, or an RF-shielded enclosure. **Nothing in this project radiates without one** — see [docs/spectrum/](spectrum/README.md) for the country matrix (please add your country).
- **People:** one student who knows Docker. No 3GPP background is assumed; the RFCs explain the why, the task files the how.

## What the project gives back

- Co-authorship on whatever your island's measurements support; the RFCs' open questions are research questions.
- A named island in the federation, your lab's name in the results, and a seat in deciding what the project becomes ([GOVERNANCE.md](../GOVERNANCE.md)).
- Honest scope: this is TRL 3–4 today, run by one maintainer with AI-assisted development, reviewed by re-running the evidence ([README](../README.md) "How the project works"). It needs labs precisely because of that.

**To start:** open an issue titled "Island: <your lab>" with your country, your radio/licence situation, and which stage you can reach — or just run QUICKSTART and file the report.
