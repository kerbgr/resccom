# Demo storyboard (WBS 1.5)

A shot list for a short screen recording of M1-sim — the human step this
task can't automate. Everything here is a command already covered by
[docs/poc-writeup.md](poc-writeup.md); this doc just orders them for a
recording and says what to point the camera at. No narration script is
mandated — the bullet under each shot is what to say or caption, not a
transcript.

**Target length:** 4-6 minutes. **Setting:** a clean terminal (large font,
dark theme, nothing in scrollback) plus a browser window, on a host that
has never run this repo before, or with `./island.sh down -v` / a fresh
clone if it has. Recording itself is a human task — nothing below runs
unattended.

## Before recording

- Pull images once beforehand (off-camera) so the recording doesn't sit on
  a multi-GB download — cite this in the video description, don't let the
  recording imply first-run speed includes it (see QUICKSTART.md's own
  timing caveat).
- Have a second terminal pane ready for `stack/backhaul/*.sh` later.
- Know the four URLs (`portal.island`, `library.island`, `chat.island`,
  `talk.island`) resolve only from a device on the UE subnet — the
  recording drives them through the UERANSIM verify path, not a host
  browser, exactly like `stack/services/verify.sh` does. Don't stage a
  browser hitting `.island` domains directly from the host; it won't
  resolve and would misrepresent how this works.

## Shot list

**1. Cold open (10-15s)**
- Terminal only. Type `git clone https://github.com/kerbgr/resccom.git &&
  cd resccom`.
- Caption/voiceover: "A private 4G/5G network for disasters and off-grid
  communities. This is the whole install."

**2. Bring-up (~2 min, real time — don't cut)**
- Run `./island.sh up`. Let it run at real speed at least once in the
  final edit (or show a clearly-labelled timelapse) — QUICKSTART's own
  measured **1m 57s** is part of the claim; speeding it up silently would
  misrepresent that number.
- While it runs, cut briefly to `stack/core/README.md` or
  `rfcs/rfc-0001-architecture.md`'s architecture diagram to explain what's
  coming up (Open5GS core, then DNS/NOMAD/Matrix/Jitsi).

**3. Verify (~45s, real time)**
- Run `stack/services/verify.sh`. Let checks scroll — the point is that
  each one is a real, named assertion (UE registration, DNS, Kiwix
  content, E2EE Matrix message, live Jitsi call, portal status), not a
  black box.
- On `ALL CHECKS PASSED`, hold the frame for a beat.

**4. What that just proved (~20s)**
- Cut to the Element Web / Jitsi containers' own logs or, if easily
  screen-capturable, the UERANSIM UE's actual browsing session — whichever
  is less fragile to demo live. Caption: "A simulated phone just
  registered onto a private cellular core and used real end-to-end
  encrypted messaging and voice — with zero internet."

**5. Pull the cable, for real (~1 min)**
- Second terminal pane. `cd stack/backhaul && ./unplug-test.sh`.
- Narrate while it runs: this isn't disconnecting a container network —
  it inserts a real, host-level firewall rule that drops every standing
  component's route to the actual internet.
- Hold on the two lines that matter: `OK: portal confirms WAN is genuinely
  unreachable` and, later, the re-run of `stack/services/verify.sh`
  reaching `ALL CHECKS PASSED` a second time — **with real WAN down**.
- Caption: "Same checks. Same result. No internet required."

**6. Close (~15s)**
- Cut to [STATUS.md](../STATUS.md) or [ROADMAP.md](../ROADMAP.md) on
  screen. Caption: "This is M1 — software only. Real radio, real
  hardware, and federation are next, and every task is open for
  reproduction." Point at the repro-report issue template and
  [CONTRIBUTING.md](../CONTRIBUTING.md).

## What NOT to show or claim

- No footage of a real phone, real SIM, or real RF — none exists yet
  (WBS 1.2-b/c/d, `[HW]`, still open). Don't stage or imply it.
- No Starlink hardware or footage — 1.4-d is open, paper design only.
- No claim of coverage, capacity, or range — no field measurement exists.
- No language suggesting the network is covert or state-adversary-proof —
  see [SECURITY.md](../SECURITY.md).
- Don't cut the bring-up/verify timings in a way that implies they're
  faster than [QUICKSTART.md](../QUICKSTART.md)'s measured numbers.

## After recording

- Publish the video, link it from this file and from
  [docs/poc-writeup.md](poc-writeup.md), and flip
  [STATUS.md](../STATUS.md)'s 1.5 row from `partial` to `done-verified`
  once it's up.
