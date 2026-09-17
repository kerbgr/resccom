# stack/services/jitsi — Jitsi Meet (1.3-d)

[Jitsi Meet](https://github.com/jitsi/docker-jitsi-meet) (Apache-2.0),
unmodified, deployed here as `talk.island` — voice/video calling, audio
verified end-to-end with real WebRTC media (see "Verification
performed"); video quality is explicitly not gated by 1.3-d's own
acceptance criteria (sim-network bandwidth isn't representative).

## Layout: five containers, two networks

`compose.yaml` is upstream's own `docker-jitsi-meet` compose file,
vendored and adapted — see its own header comment for the precise diff
from upstream. Five services:

- `prosody` (XMPP signaling), `jicofo` (conference focus) — private
  `meet.jitsi` network only, never reachable from `services_net`.
- `web` — private `meet.jitsi` network only. Not multi-homed like
  `matrix-synapse`'s HTTP counterpart: see "Why jitsi-gateway terminates
  TLS" below for why it's reached through a proxy instead.
- `jvb` (the video bridge) and `coturn` (STUN/TURN, 1.3-d's own
  addition — upstream doesn't ship one) — **directly** on `services_net`,
  at fixed addresses (`10.46.0.31`, `10.46.0.32`). Not proxied: WebRTC's
  actual media (JVB) and TURN relay allocations (coturn) are UDP flows a
  browser opens directly to a real, stable address — an HTTP-layer
  reverse proxy can front `web`'s signaling, never this.
- `jitsi-gateway` (our own glue, added here rather than in
  `../compose.yaml` because it needs to join `web`'s private
  `meet.jitsi` network to reach it) — the only thing at `talk.island`
  (`10.46.0.30`) on `services_net`.

## Why jitsi-gateway terminates TLS

Every other `.island` service in this repo is plain HTTP — deliberately,
to keep the lab profile simple. Jitsi can't be: browsers refuse to expose
`getUserMedia()`/`RTCPeerConnection` at all on an origin that isn't a
"secure context" (HTTPS, or literally `localhost`), and `talk.island`
over plain HTTP is neither. This isn't a Jitsi-side check to route
around — it's the browser itself. Confirmed live during development: a
headless Chromium pointed at `http://talk.island` rendered "WebRTC is not
available in your browser" instead of a Jitsi Meet error.

`jitsi-gateway` terminates TLS with a **self-signed** certificate
(`data/jitsi-gateway/cert.{crt,key}`, gitignored, generated once — see
"Bring-up"). That's enough to satisfy the browser's secure-context check,
but it isn't a real, CA-trusted certificate — a real browser shows a
one-time "your connection isn't private" warning a user has to click
through. That's an honest placeholder for real PKI (WBS 3.4, Phase 3),
not a security claim; see [SECURITY.md](../../../SECURITY.md). `web`
itself stays `DISABLE_HTTPS=1` (plain HTTP to the gateway, matching every
other backend in this repo) — TLS exists only at the one edge that
structurally needs it.

## STUN/TURN scoped to local subnets (1.3-d's own wording)

Upstream's documented answer for an offline/LAN Jitsi deployment is
`JVB_DISABLE_STUN=true` — skip STUN's "discover my public IP" step
entirely, since there's no public IP to discover. That alone would leave
`JVB_STUN_SERVERS` at its default (Google's public STUN servers) as a
latent WAN dependency nothing here would ever trip during simulation but
a real deployment absolutely could. Instead: `coturn` (STUN/TURN,
upstream doesn't ship one) is deployed here, and every STUN/TURN hint
Jitsi hands to a browser (`JVB_STUN_SERVERS`, `STUN_HOST`, `TURN_HOST`)
points at it — never Google's servers, not even as an unused default. Its
`command:` in `compose.yaml` adds `--denied-peer-ip=0.0.0.0-
255.255.255.255` then carves out `--allowed-peer-ip` for just
`10.45.0.0/16` (UE) and `10.46.0.0/24` (services): a TURN allocation on
this server can never be used to relay traffic anywhere but this island's
own subnets, WAN included, regardless of what a client asks for.

`--lt-cred-mech --use-auth-secret --static-auth-secret=$TURN_CREDENTIALS`
implements the TURN REST API's shared-secret scheme (time-limited HMAC
credentials Prosody's `mod_turncredentials` hands out per-session) —
not a single hardcoded username/password.

## Bring-up

```bash
cd stack/services/jitsi
cp jitsi.example.env .env   # then edit every value — see the file's own comments
mkdir -p ../data/jitsi-gateway
openssl req -new -x509 -days 3650 -nodes \
  -out ../data/jitsi-gateway/cert.crt -keyout ../data/jitsi-gateway/cert.key \
  -subj "/CN=talk.island" -addext "subjectAltName=DNS:talk.island"
docker compose up -d
```

`talk.island` (`https://`, self-signed — see above) serves Element Web's
counterpart here: join `https://talk.island/<any-room-name>` from two
browsers to test by hand. No authentication is configured (matches
1.3-d's own scope; access-control policy for a real deployment is an
operator/playbook decision, same caveat as chat.island's open
registration in `../README.md`).

## Versions

| Component | Image | Tag | Notes |
|---|---|---|---|
| Jitsi Meet (web/prosody/jicofo/jvb) | `ghcr.io/jitsi/*` | `stable-11146-2` | Official images, pinned via `JITSI_IMAGE_VERSION` in `.env`. Multi-arch. |
| coturn | `coturn/coturn` | `4.18.0` | Official image. Multi-arch. |
| jitsi-gateway | `nginx` | `1.27.5-alpine` | Same pin as `nomad-gateway`/`matrix-gateway` in `../compose.yaml`. |

<!-- VERIFY: re-check these tags periodically; jitsi/docker-jitsi-meet's
GitHub tags and coturn/coturn's Docker Hub page are the sources of truth. -->

## Known limitations / design notes

- **Self-signed TLS, not real PKI.** See "Why jitsi-gateway terminates
  TLS" above.
- **Open access, no auth configured.** See "Bring-up" above.
- **`jvb`'s `JVB_ADVERTISE_IPS` is a single fixed address**
  (`10.46.0.31`), correct for this lab topology (one UPF NAT hop, one
  services subnet) but not something that generalizes automatically to
  every `node-hw/` class without review — a node with a more complex
  local topology (multiple radios, mesh backhaul) may need more than one
  advertised address.
- **coturn's relay port range is narrow** (`49152-49200`, ~48 ports) —
  plenty for this task's 2-participant verification, undersized for a
  real multi-call island; widen it for an actual deployment.
- **Host port 8080 collision with NOMAD.** `jvb`'s upstream-default
  Colibri debug port (127.0.0.1-only, operator convenience, never used
  by the UE) collided with NOMAD's admin dashboard on this same dev
  host — moved to `18080` via `JVB_COLIBRI_PORT`. Arbitrary choice, not
  a meaningful value.

## Verification performed

Deployed on this machine (macOS + Docker Desktop, `linux/amd64`
emulation for the Jitsi images, native for coturn/nginx). Three real
mistakes surfaced and got fixed before landing:

1. **Host port 8080 collision.** `jvb`'s Colibri port publish failed
   outright (`port is already allocated`) against NOMAD's admin
   dashboard already using it — moved to `JVB_COLIBRI_PORT=18080`.
2. **coturn's `--no-dtls` flag doesn't exist** in coturn 4.18.0
   (crash-looped printing its own `--help` until this was noticed in the
   logs) — DTLS turned out to be opt-in via a separate `--dtls` flag this
   deployment never passes, so `--no-tls` alone was already sufficient;
   removed the invalid flag.
3. **The secure-context / self-signed TLS chain above** — the biggest
   one. First deploy was plain HTTP (`DISABLE_HTTPS=1`, matching every
   other component); a headless-browser test against it showed Jitsi's
   own "WebRTC is not available in your browser" screen. Root-caused to
   the browser's secure-context restriction (not a Jitsi or network
   misconfiguration), fixed by adding TLS termination at `jitsi-gateway`
   with a self-signed cert.

**The audio call check itself** (`../verify-jitsi-call.js`, run by
`../verify.sh`'s check 7): two headless-Chromium participants, each with
Chromium's synthetic fake audio/video device
(`--use-fake-device-for-media-stream`), join the same room with
`config.p2p.enabled=false` (forcing the JVB media path — the one a real
multi-person call, and often a 2-person one, actually uses). Verified via
real `RTCPeerConnection.getStats()` — not "both showed as joined" — that
each side has a non-empty `inbound-rtp`/`audio` report with a non-zero
`audioLevel`, and that `packetsReceived` actually grows over a 5-second
window (ruling out a stale snapshot from a call that connected and then
went silent). Confirmed both directions:

```
Alice inbound audio: packetsReceived 622 -> 842 (growth 220), audioLevel 0.0156
Bob inbound audio:   packetsReceived 619 -> 839 (growth 220), audioLevel 0.097
```

**Run from inside the UE's own network namespace**
(`docker run --network container:core-ue-1 ...`), not just a
`services_net` container reaching the same DNS names — the most literal
reading of the acceptance criterion's "on the UE subnet". This surfaced a
real design gap during development: `npm install playwright` (needed to
fetch the test driver — this repo doesn't vendor it) genuinely cannot run
inside that namespace (`ENETUNREACH` — `core_net` has no WAN route at
all, by construction), which is exactly why `../verify.sh` installs into
a reusable named volume from a `services_net` container first, then runs
the actual test — with no further installation — sharing the UE's
namespace. That failure is also incidental proof of something worth
recording: the working audio call above ran with *zero WAN path
available* to that namespace, not merely "WAN happened to be
disconnected when tested."

Re-ran `../../core/verify.sh` end-to-end after all of the above: still
`ALL CHECKS PASSED`, no regression.
