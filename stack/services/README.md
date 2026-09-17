# stack/services — island service layer (1.3-a: local DNS, 1.3-b: NOMAD, 1.3-c: Matrix, 1.3-d: Jitsi, 1.3-e: portal, 1.3-f: one-command bring-up)

The services subnet (`10.46.0.0/24`, CLAUDE.md convention), a small
authoritative-for-`.island` DNS resolver (1.3-a), Project NOMAD's
knowledge library reachable at `library.island` (1.3-b, see
[`nomad/README.md`](nomad/README.md) for that component specifically),
a Matrix homeserver + Element Web at `chat.island` with E2EE on by
default (1.3-c), Jitsi Meet voice/video at `talk.island` (1.3-d, see
[`jitsi/README.md`](jitsi/README.md)), and a live status/landing page at
`portal.island` that's also where every other domain resolves when the
island's WAN link is down (1.3-e). One-command bring-up (1.3-f) is next.

No radio hardware involved anywhere here — this is the `[SIM]` path per
[CLAUDE.md](../../CLAUDE.md).

## How the services subnet reaches the UE

`services_net` isn't created by this component — it's created by
[`../core/compose.yaml`](../core/compose.yaml), because UPF is this
subnet's router:

- UPF already owns the UE's PDU-session gateway (`10.45.0.1` on `ogstun`)
  and already forwards.
- 1.3-a joins UPF to `services_net` as well, at `10.46.0.2`, and turns on
  `ENABLE_NAT` — the image's own unmodified entrypoint turns that into one
  iptables rule, `-t nat -A POSTROUTING -s 10.45.0.0/16 ! -o ogstun -j
  MASQUERADE`, which only matches UE-subnet traffic leaving by a
  non-`ogstun` interface (i.e. breakout to services).
- Practical effect: a services container (this DNS server, and everything
  that lands here later) never needs to know the UE subnet exists at all.
  It just sees traffic from `10.46.0.2` (UPF) and replies to that; UPF's
  own conntrack un-NATs the reply back into `ogstun` to the right UE. No
  service container needs a static route back to `10.45.0.0/16`, and none
  of this is visible in this directory's own compose file.
- `stack/services/compose.yaml` attaches to `services_net` as `external`
  (fixed network name `resccom_services_net`) — core must be up first,
  which is already `island.sh`'s intended order (1.3-f).

This was a real design choice, not the only one: the alternative was
having UPF act as a classic default-gateway router (hold the subnet's
`.1` address, no NAT, every services container gets a static route back
to `10.45.0.0/16`). Rejected because: (a) Docker's bridge driver always
claims the first address of a network's subnet for its own host-side
gateway veth, so UPF can't hold `10.46.0.1` anyway; and (b) NAT means
zero per-service routing config, now or for any future service added
here — a real win as this directory grows to 1.3-b..e.

**Not "on wheels" security theater**: this NAT is purely a same-host
routing convenience between two subnets one router (UPF) owns end to end.
It has nothing to do with the actual security/threat-model boundary in
[SECURITY.md](../../SECURITY.md) — no traffic here crosses to another
island or the WAN because of it.

## The `.island` zone

CoreDNS, authoritative for `.island` via a real zone file (`file` plugin,
not `hosts`) — `config/coredns/island.zone` has an SOA/NS record and one
A record per name. A real zone was chosen over the simpler `hosts` file
approach specifically so an unmatched name comes back a clean, standards-
correct `NXDOMAIN` from CoreDNS itself, never a bare miss into the next
plugin (`hosts` gave `SERVFAIL` for unmatched names in testing —
indistinguishable from "WAN is down", which is the one failure mode this
task needs to keep unambiguous).

All records are real as of 1.3-b/1.3-c/1.3-d/1.3-e:

| Name | Address | Backing service |
|---|---|---|
| `portal.island` | `10.46.0.10` | Landing/status page (1.3-e) — see below |
| `library.island`, `learn.island`, `maps.island` | `10.46.0.11` | NOMAD (1.3-b) — currently all three answer with Kiwix; see [`nomad/README.md`](nomad/README.md) |
| `chat.island` | `10.46.0.20` | Matrix homeserver + Element Web (1.3-c) |
| `talk.island` | `10.46.0.30` | Jitsi Meet (1.3-d) — see [`jitsi/README.md`](jitsi/README.md) |
| `ns.island` | `10.46.0.53` | This DNS server |

A second, independent server block (`.` in `config/coredns/Corefile`)
forwards everything else to WAN resolvers (`1.1.1.1`, `9.9.9.9`) with
`cache`. These two blocks are deliberately **not** one zone with a
`fallthrough` from `.island` to the forwarder: `.island` must resolve
identically whether the WAN uplink is up or down (CLAUDE.md: local-only,
never routed between islands), so it cannot share a code path — let alone
a failure path — with the forwarder.

`forward`'s `max_fails 1` / `expire 10s` / `health_check 5s` mark a dead
upstream unhealthy after one failed attempt rather than retrying it into
a multi-second stall. Measured (see "Verification performed"): a single
query against an unreachable forwarder returns `SERVFAIL` in ~2s, not a
hang — that was true through 1.3-d; as of 1.3-e it resolves to
`portal.island` instead (below), on the same timeline.

**1.3-e's "resolve-anything fallback when WAN is down"** is the third
entry in that same `forward` upstream list, not a separate mechanism:
`forward . 1.1.1.1 9.9.9.9 127.0.0.1:5353 { policy sequential ... }`.
`policy sequential` is what makes this work — a stock, documented
`forward` behavior (try upstreams in order, move on when one fails), not
something layered on top of it. `127.0.0.1:5353` is a second, loopback-
only server block in the same Corefile/container that unconditionally
answers every A query with `portal.island`'s address — so once
`1.1.1.1`/`9.9.9.9` are both marked unhealthy, any query for any domain
lands there instead of SERVFAIL. Verified empirically before trusting
it: an isolated CoreDNS instance with unreachable upstreams really does
fall through to the loopback answer, not a documentation assumption —
see "Verification performed".

## Project NOMAD (1.3-b)

`library.island` (and, for now, `learn.island`/`maps.island` too) serves
Project NOMAD's Kiwix-backed knowledge library. NOMAD runs as its own
compose project in [`nomad/`](nomad/) — see
[`nomad/README.md`](nomad/README.md) for what it is, why it's a separate
compose project instead of a service in this file, and how a small nginx
proxy (`nomad-gateway`, below) bridges the two without ever attaching
anything of NOMAD's to `services_net` directly.

```nginx
server {
    listen 80 default_server;
    location / { proxy_pass http://host.docker.internal:8090; ... }
}
```

(`config/nomad-gateway/nginx.conf` in full) — every request landing on
`10.46.0.11` goes to Kiwix's host-published port, regardless of which of
the three names resolved it there.

## Matrix: chat.island (1.3-c)

**Synapse, not Dendrite.** The task called for evaluating both; CLAUDE.md
already settles it by naming Synapse specifically among this project's
fixed upstreams, and current state backs that up independent of the
pre-existing constraint: Dendrite is in maintenance mode (security fixes
only) as of this writing, which is disqualifying for infrastructure
meant to keep running, isolated, for years — Synapse remains the
actively-developed reference implementation with the most-tested E2EE
and cross-signing support, despite a heavier footprint than Dendrite's
(acceptable for `node-hw`'s target classes; see "Known limitations").

**Postgres, not SQLite.** Upstream's own docs call SQLite "not
recommended for production usage"; `matrix-postgres` runs on a private
`matrix_net` that nothing else can reach (see the compose file's own
header comment) — same least-exposure shape as `core_net`, scoped to
just this one component.

**Config is split in two, not committed whole.** `config/matrix-synapse/
homeserver.yaml` (committed) holds everything non-secret; secrets
(`registration_shared_secret`, `macaroon_secret_key`, `form_secret`, the
Postgres password) live in `data/matrix-synapse/secrets.yaml`
(gitignored — `secrets.example.yaml` is the checked-in template), and
Synapse is started with both: `run -c homeserver.yaml -c secrets.yaml`.
Synapse's config format has no `${VAR}`-style substitution, so this was
the only way to keep secrets out of git without hand-rolling a templating
step — verified live that Synapse actually deep-merges multiple `-c`
files at real startup (see "Verification performed"; a debug subcommand,
`synapse.config read <key> -c a -c b`, misleadingly suggested it
*doesn't* merge — trust the real `run` behavior over that).

**Federation is prepared, not enabled** (1.3-c's own wording). Two
things enforce this, deliberately redundant: the client listener in
`homeserver.yaml` has no federation resource attached at all — there is
no federation endpoint for anything to reach, the same "no path exists"
posture `core_net`'s `internal: true` takes — and
`federation_domain_whitelist: []`, upstream's own documented way to deny
federation with every server. `server_name: chat.island` is nonetheless a
real, stable value (not `localhost`), so turning federation on later
(Phase 4, RFC-0005's per-island identity/registry) won't require
re-provisioning every existing user's identity.

**E2EE is on by default, not opt-in** — SECURITY.md commits to this as a
property that must not silently regress. `homeserver.yaml` sets
`encryption_enabled_by_default_for_room_type: all`: every locally-created
room gets a real `m.room.encryption` state event at creation, with no
client-side toggle needed. Verified with actual Olm/Megolm crypto, not
just "a message arrived" — see "Verification performed".

**Registration is open, no email** (1.3-c's own wording: "local
registration, no email verification"). `enable_registration: true` +
`enable_registration_without_verification: true`; upstream's own docs
call this combination "not recommended" as a public-internet spam/abuse
vector — accepted here because this homeserver has no path to the WAN to
be abused from (see the federation point above, and SECURITY.md's threat
model, which scopes adversaries to the local network). A real multi-
island deployment may want `registration_shared_secret`-gated,
operator-issued registration instead of open self-service — a playbook
policy decision, not something this task hardcodes.

**One origin, not two.** `matrix-gateway` (nginx, `10.46.0.20`, the only
piece of this component on `services_net` — `matrix-synapse` and
`matrix-element` stay on the private `matrix_net`) proxies `/_matrix` and
`/_synapse/client` to Synapse and everything else to Element Web, so the
browser's client API calls and the webapp it loaded share one
origin/port — no CORS involved at all. This is the standard co-located
Matrix deployment topology, not something specific to this repo.

## Jitsi Meet: talk.island (1.3-d)

Full detail in [`jitsi/README.md`](jitsi/README.md) — its own compose
project (like NOMAD, unlike Matrix, since it's five containers with a
large upstream-defined config surface worth keeping separate). Two
points worth knowing before following a link:

- **This is the one `.island` service that needs TLS**, and gets it
  (self-signed) at `jitsi-gateway` — every other component in this
  directory is deliberately plain HTTP, but browsers refuse WebRTC
  entirely on a non-secure-context origin, which plain HTTP over a LAN
  hostname is. Not optional, not a style choice; see `jitsi/README.md`'s
  own "Why jitsi-gateway terminates TLS".
- **`jvb` and `coturn` sit directly on `services_net`** (not behind a
  proxy, unlike `web`) — WebRTC's actual UDP media and TURN relay
  allocations need a real, stable, directly-routable address a browser
  opens a UDP flow to; an HTTP-layer reverse proxy can front signaling,
  never that.

## Portal: portal.island (1.3-e)

`config/portal/server.py` — stdlib-only Python (no pip install, no build
step) run directly against the stock `python` image, the same "mount a
script into an unmodified upstream image" pattern every other component
here uses. Two things make it different from a plain static page:

- **Status is server-rendered, not client-fetched.** The health of
  `library.island`/`chat.island`/`talk.island`/local DNS, and whether the
  island currently has a WAN uplink, is computed fresh and written
  directly into the HTML on every `GET /` — not loaded afterward by
  client-side JS. That's what lets 1.3-e's own acceptance test
  (`curl http://portal.island`, no JS execution at all) see live,
  correct status, and it's also why the page still works correctly with
  JavaScript disabled entirely (1.3-e's own "must render on a five-year-
  old Android browser": no fetch, no build step, no external assets —
  everything, including the CSS, is inlined in the one response). A
  `GET /status` JSON endpoint exposes the same computed data for
  scripted checks (`verify.sh`); the page's own only JS is a 15-second
  reload timer.
- **It's also where the internet goes when the internet isn't there.**
  Every request gets the same page regardless of path or `Host` header —
  which is exactly what lets it double as the destination CoreDNS's WAN-
  down fallback (above) sends every other domain to, the same
  "resolve-anything" behavior a commercial captive portal gives you.

`[local association name]` and the operator-contact section render from
`data/portal/settings.json` (`island-init render`, 2.1-b — see
`server.py`'s `load_settings()`), falling back to the original bracketed
placeholder text when null. The lab profile's `island.yaml` leaves both
null (real values are an association/`playbook/` concern,
`playbook/authorities.md`, not yet written); a real deployment fills
them in via the Island Console below or `island-init new`'s prompts.
`data/portal/settings.json` is gitignored, not `config/` (2.1-g): it's a
per-deployment output of whatever `island.yaml` render was pointed at, and
`island.sh up` renders it fresh on every boot (`render_instance_outputs`)
so the bind mount below always finds a real file, even on a brand-new
checkout — see [island-init/README.md](../../island-init/README.md)'s own
note on this and the tracked `settings.example.json` golden-rule fixture.

## Island Console: console.island (2.1-d, hardened 2.1-f)

`config/console/` — the map-based editor over `island.yaml` (RFC-0006).
A custom-built Python backend (`server.py`, `Dockerfile`) that imports
`island_init` directly (the same schema/render code `island-init
check`/`render` use — see the Dockerfile's own header comment for why:
it's what makes "render --diff from the console equals the CLI's
output" true by construction), plus a plain-JS/MapLibre GL frontend
(`static/`) with no build step.

- **Map tiles**: `maps.island` (`config/nomad-gateway/nginx.conf`) serves
  the PMTiles file NOMAD's own Maps feature already produces
  (`nomad/data/storage/maps/pmtiles/world.pmtiles`, via its
  `setup-world-basemap` API) directly off their shared bind mount — no
  second map/tile stack, per RFC-0006 D2. `static/style.json` is derived
  from NOMAD's own downloaded Protomaps basemap style with label/icon
  (`symbol`) layers stripped, since no glyph/sprite server is vendored
  alongside it (fill/line/circle layers render fine without them). Only
  a coarse z0-5 world extract is provisioned by default — good enough to
  place a site on a map, not for street-level survey; an operator
  downloads a finer regional extract through NOMAD's own admin UI.
- **MapLibre GL JS v4.7.1** and **PMTiles JS v4.5.0** (`config/console/vendor/`,
  both BSD-3-Clause) are vendored as plain UMD `<script>` bundles, not
  fetched from a CDN at runtime — MapLibre v4.x is the last release with
  a single-file UMD build; v5+ ships ESM-only with a module Worker, which
  isn't as reliably supported on an older Android WebView.
- **Editor**: the frontend loads the whole `island.yaml` document as one
  JS object, binds form fields and map interactions to it directly, and
  posts the *entire* candidate document back to `/api/preview` (dry-run,
  returns the same diff text `island-init render --diff` would) or
  `/api/draft` ("Save draft"). `island.id`/the signing keypair/the
  WireGuard key are always re-derived from what's already on disk
  server-side — a posted edit can never change them.
- **Draft / host-apply split (2.1-f, RFC-0006 D5)**: this container never
  signs anything, never writes `island.yaml`, and never restarts a
  service. "Save draft" validates the candidate and, if clean, stages it
  (unsigned) to `data/console/draft.yaml`, logging the timestamp to
  `data/console/console-draft.log`; `GET /api/draft` reports whether one
  is pending. An operator runs `./island.sh apply` **on the node host**
  to sign it with the key that never leaves the host
  (`island_init.apply.apply_draft`), render, write `island.yaml`, and
  restart only the containers whose rendered config actually changed
  (`island_init.apply.RESTART_MAP`, via a plain `docker restart` the
  host already has — no socket handed to the container), logging the
  apply itself to `data/console/console-apply.log`. See
  `stack/services/config/console/server.py`'s and
  `island-init/island_init/apply.py`'s own header comments.
- **Coverage**: *predicted* (`config/console/coverage.py`) is a named,
  documented Okumura-Hata urban model computed live from a cell's real
  `tx_power_dbm`/band/site height — a cell with `tx_power_dbm: null`
  (every RAN rig in the lab profile: ZMQ/rfsimulator have no real
  transmit power) simply has no predicted layer, never an invented
  number. *Measured* is an operator-uploaded CSV
  (`lat,lon,rsrp,rsrq,timestamp`), stored under `data/console/measured/`
  and referenced from the cell's `measured_points.file_ref`. The two are
  rendered with a hatched red fill + a permanent "predicted (model: …) —
  not measured" legend vs. plain blue points — never the same style.
  `portal.island` shows neither (it has no map at all), so "no coverage
  claim without measured data" holds by construction.
- **Auth (2.1-f)**: a per-boot operator token, generated by `island.sh
  up` and printed once (also written to
  `data/console/operator-token`, `chmod 600`), is required on every
  write endpoint (`POST /api/preview`, `/api/draft`, `/api/measured/*`)
  via `Authorization: Bearer <token>`, checked with `hmac.compare_digest`.
  Read-only endpoints (map tiles, `/api/island`, `/api/coverage/*`,
  `/api/draft`'s own GET) need no token — still lab-grade (a fresh token
  each `up`, no per-operator identity, no HTTPS in front of it), the
  WBS 3.4 hook SECURITY.md's lab-profile register row points at.

Verified live end-to-end via `verify-console.js`
(`mcr.microsoft.com/playwright:v1.63.0-noble`, run against
`--network container:core-ue-1` — the same UE-subnet pattern
`verify-jitsi-call.js` uses, with the operator token passed in via
`OPERATOR_TOKEN` — see that file's own header comment): loads
`console.island`, confirms the map actually rendered features from the
local tiles, confirms every write endpoint 401s with no token and with
the wrong one, places a site + cell, runs Preview and Save Draft with
the real token, and confirms the console reports a pending draft.
Applying that draft (signing, rendering, restarting) is the host-side
`island.sh apply` step 2.1-f moved out of the browser's reach entirely —
run separately, then confirmed the same way 2.1-d always was:
`island.yaml` on disk passes `island-init check` (signature included),
and tampering one byte of it afterward makes `check` fail.

## Bring-up

**The top-level [`island.sh`](../../island.sh) (1.3-f) does all of this
automatically** — core, then NOMAD (Kiwix has to exist before
`nomad-gateway` can report healthy — see its own header comment for why
that ordering matters), then this directory's own compose project,
then Jitsi, generating every secret/cert on a first run from the
`*.example.*` templates referenced below. What follows here is the
manual, step-by-step equivalent — useful for understanding or
customizing one component at a time, not the normal way to bring this
up.

```bash
cd stack/core && docker compose up -d      # must be up first — see above
cd ../services
cp matrix.example.env .env                 # then edit — MATRIX_DB_PASSWORD
cp config/matrix-synapse/secrets.example.yaml data/matrix-synapse/secrets.yaml
# then edit data/matrix-synapse/secrets.yaml: registration_shared_secret /
# macaroon_secret_key / form_secret (any long random string — Synapse's
# own `generate` command is the simplest correct way to produce these,
# see README's "Config is split in two" above) and database.args.password
# (must equal .env's MATRIX_DB_PASSWORD)
docker compose up -d                       # dns + portal + nomad-gateway + matrix
cd nomad && cp nomad.example.env .env      # then edit — see nomad/README.md
docker compose up -d                       # admin + mysql + redis
# install Kiwix and preload its bundled demo ZIM — see nomad/README.md
curl -s -X POST http://localhost:8080/api/system/services/install \
  -H 'Content-Type: application/json' -d '{"service_name":"nomad_kiwix_server"}'
cd ../jitsi && cp jitsi.example.env .env   # then edit — see jitsi/README.md
mkdir -p ../data/jitsi-gateway
openssl req -new -x509 -days 3650 -nodes \
  -out ../data/jitsi-gateway/cert.crt -keyout ../data/jitsi-gateway/cert.key \
  -subj "/CN=talk.island" -addext "subjectAltName=DNS:talk.island"
docker compose up -d                       # web + prosody + jicofo + jvb + coturn + gateway
```

Query it directly from the host (simplest smoke test, no UE needed):

```bash
docker run --rm --network resccom_services_net alpine \
  sh -c "apk add --no-cache bind-tools >/dev/null && dig +short portal.island @10.46.0.53"
  # -> 10.46.0.10
```

Or from the simulated UE, which is what 1.3-a/1.3-b's acceptance criteria
actually check:

```bash
cd stack/core
docker compose -f compose.yaml -f compose.sim.yaml exec ue \
  ip route add 10.46.0.0/24 dev uesimtun0   # not auto-installed by nr-ue
docker compose -f compose.yaml -f compose.sim.yaml exec ue \
  dig +short portal.island @10.46.0.53      # -> 10.46.0.10
# a real device gets 10.46.0.53 pushed as its DNS server via PCO; the sim
# UE doesn't, so point its resolver there directly to test plain curl:
docker compose -f compose.yaml -f compose.sim.yaml exec ue \
  sh -c "echo 'nameserver 10.46.0.53' > /etc/resolv.conf"
docker compose -f compose.yaml -f compose.sim.yaml exec ue \
  curl -s http://library.island/   # -> Kiwix's landing page
```

chat.island's acceptance criterion ("two accounts created from the UE
subnet exchange E2EE messages") needs real Olm/Megolm crypto, which
`curl`/`dig` can't do — `verify-matrix-e2ee.py` (run inside a throwaway
`python:3.12-slim` container with `matrix-nio[e2e]` + `httpx` installed,
on `services_net` so it reaches `chat.island` the same way the UE does)
registers two fresh accounts, sends a real encrypted message, decrypts it
with an independent client, and separately confirms over the raw
client-server API that the server actually stored ciphertext. See its own
docstring, and "Verification performed" below for what this caught.

talk.island's acceptance criterion ("two browser clients ... hold an
audio call") needs real WebRTC media, further still from `curl`/`dig`
than Matrix's crypto check was — `verify-jitsi-call.js` (run with
`playwright` inside a throwaway `mcr.microsoft.com/playwright` container,
sharing the actual UE container's network namespace via `--network
container:core-ue-1` — the most literal reading of "on the UE subnet")
launches two headless-Chromium participants with synthetic fake
audio/video devices, joins them to the same room, and reads real
`RTCPeerConnection.getStats()` from both sides to confirm live,
growing, non-silent inbound audio RTP — not just "both showed as
joined". See its own docstring, and `jitsi/README.md`'s "Verification
performed" for what this caught (including why the test needs two
separate containers, not one).

portal.island's acceptance criterion ("shows correct live status with
WAN both up and down") is the one check in this file `verify.sh` doesn't
run for you, on purpose — see the WAN-up half below and
"Verification performed" for the WAN-down half, done manually the same
way 1.3-a's own forward-failure simulation was:

```bash
cd stack/core
docker compose -f compose.yaml -f compose.sim.yaml exec ue \
  curl -s http://portal.island/   # -> the live status page, WAN up
docker compose -f compose.yaml -f compose.sim.yaml exec ue \
  curl -s http://portal.island/status   # -> the same data as JSON
```

`./verify.sh` in this directory automates all of the above end-to-end:
bring-up itself now just delegates to [`../../island.sh`](../../island.sh)
(1.3-f), then it brings up the UERANSIM UE and runs the route/dig/curl/
Matrix-E2EE/Jitsi-audio/portal-status checks on top. This is also how
1.3-f's own acceptance criterion — "island.sh up" leading to a UE that
registers, browses library.island, and sends an E2EE message — gets
exercised: this script *is* that scenario, automated.

## Layout

- `compose.yaml` — `dns`, `portal`, `nomad-gateway`, and the Matrix stack
  (`matrix-postgres`, `matrix-synapse`, `matrix-element`,
  `matrix-gateway`), attached to the `services_net` network `stack/core`
  owns (`external: true` here) plus a private `matrix_net` for Postgres.
- `config/coredns/Corefile` — the three server blocks described above.
- `config/coredns/island.zone` — the authoritative `.island` zone file.
- `config/portal/server.py` — portal.island's page + status logic; see
  "Portal: portal.island" above.
- `config/nomad-gateway/nginx.conf` — the NOMAD proxy glue, see "Project
  NOMAD (1.3-b)" above.
- `config/matrix-synapse/homeserver.yaml` — Synapse's non-secret config;
  `secrets.example.yaml` is the template for the gitignored
  `data/matrix-synapse/secrets.yaml` — see "Matrix: chat.island" above.
- `config/matrix-element/config.json` — Element Web's config, pointing at
  `chat.island` with no external integrations/identity server.
- `config/matrix-gateway/nginx.conf` — the single-origin Matrix proxy glue.
- `matrix.example.env` — template for this directory's own gitignored
  `.env` (currently just `MATRIX_DB_PASSWORD`).
- `verify-matrix-e2ee.py` — the real-crypto Matrix E2EE check, run by
  `verify.sh` inside a throwaway container (see "Bring-up" above).
- `verify-jitsi-call.js` — the real-WebRTC Jitsi audio call check, run by
  `verify.sh` inside a throwaway container (see "Bring-up" above).
- `nomad/` — Project NOMAD's own compose project; see
  [`nomad/README.md`](nomad/README.md).
- `jitsi/` — Jitsi Meet's own compose project; see
  [`jitsi/README.md`](jitsi/README.md).
- `verify.sh` — delegates bring-up to [`../../island.sh`](../../island.sh)
  (1.3-f), then brings up the UERANSIM UE and runs the
  1.3-a/1.3-b/1.3-c/1.3-d/1.3-e acceptance checks.
- `config/console/` — the Island Console (2.1-d); `server.py` +
  `coverage.py` + `Dockerfile` (backend, imports `island_init` directly),
  `static/` (frontend: `index.html`, `app.js`, `style.css`, `style.json`),
  `vendor/` (MapLibre GL JS, PMTiles JS — see "Island Console" above and
  "Versions" below).
- `verify-console.js` — the live-browser Island Console check, run the
  same way `verify-jitsi-call.js` is (see "Island Console" above).

## Versions

| Component | Image | Tag | Notes |
|---|---|---|---|
| CoreDNS | `coredns/coredns` | `1.12.1` | Official image. Multi-arch (amd64/arm64/...) — unlike `gradiant/open5gs`, no platform pin needed. |
| nginx | `nginx` | `1.27.5-alpine` | The `nomad-gateway` and `matrix-gateway` proxies. Multi-arch. |
| Synapse | `ghcr.io/element-hq/synapse` | `v1.160.0` | Official image. Multi-arch. |
| Element Web | `ghcr.io/element-hq/element-web` | `v1.12.27` | Official image. Multi-arch. |
| Postgres | `postgres` | `16.10-alpine` | Synapse's backing store. Multi-arch. |
| Python | `python` | `3.12.11-alpine3.21` | `portal`'s runtime — stdlib only, nothing installed on top. Multi-arch. |
| Python (console) | `python` | `3.12.11-alpine3.21` | `config/console/Dockerfile`'s base — same pin as portal, but with `island_init`'s own pip dependencies installed on top (click 8.1.8, jsonschema 4.23.0, ruamel.yaml 0.18.6, jinja2 3.1.6, cryptography 50.0.1 — kept identical to `island-init/pyproject.toml`). |
| MapLibre GL JS | vendored | `4.7.1` | `config/console/vendor/maplibre-gl.{js,css}`, BSD-3-Clause. Pinned below v5's ESM-only/module-Worker switch for older-Android compatibility (2.1-d's own "must render on a five-year-old Android browser" bar). |
| PMTiles JS | vendored | `4.5.0` | `config/console/vendor/pmtiles.js`, BSD-3-Clause. |
| NOMAD Maps basemap style | derived | n/a | `config/console/static/style.json`, hand-derived from `nomad/data/storage/maps/nomad-base-styles.json` (itself Protomaps' basemaps style, BSD-3-Clause) — see that file's own `_comment`. |

Jitsi Meet's own versions (web/prosody/jicofo/jvb/coturn/jitsi-gateway)
are pinned in [`jitsi/README.md`](jitsi/README.md), not here.

Project NOMAD's own versions (admin/MySQL/Redis/Kiwix Serve) are pinned
in [`nomad/README.md`](nomad/README.md), not here.

<!-- VERIFY: re-check these tags periodically; coredns.io, nginx's Docker
Hub page, element-hq/synapse and element-hq/element-web's GitHub release
pages, and nomad/README.md's own sources are the sources of truth. -->

## Known limitations / design notes

- **`services_net` is not `internal: true`.** Unlike `core_net`, this
  subnet is expected to want an optional WAN path (the DNS forwarder here,
  and likely Matrix/Jitsi update or federation traffic later) — whether
  that path is actually up is `stack/backhaul`'s concern (1.4), not
  something this component should hardcode either way.
- **`[local association name]` and the operator-contact section on
  portal.island are placeholders**, deliberately — see "Portal:
  portal.island" above.
- **No literal "unplug the cable" WAN-down test as of 1.3** — true of
  every WAN-down claim in this directory at the time. What was done
  instead, every time: temporarily point the relevant check at a
  genuinely unreachable address (Class E, `240.0.0.0/8`, never routed)
  rather than a real one that merely happens to be down right now,
  confirm the failure path behaves correctly, then revert. 1.3-e's
  version of this is the most thorough of those — see "Verification
  performed" below, which exercises the actual DNS fallback and the
  portal's own WAN probe together, from the real UE. (The NOMAD/Kiwix
  path added in 1.3-b, the Matrix path added in 1.3-c, and the Jitsi
  call path added in 1.3-d, have no WAN dependency to test either way —
  see `nomad/README.md`'s own note, "Matrix: chat.island"'s federation
  point above, and 1.3-d's own incidental proof of this in its
  "Verification performed".) **This gap is now closed**:
  [`../backhaul/unplug-test.sh`](../backhaul/README.md#the-unplug-test-14-b)
  (1.4-b) drops real WAN routes at the host level for the whole island
  and re-runs `verify.sh` (this file) against that — the actual test the
  paragraph above describes not having. That required one small,
  backward-compatible fix here: check 8 below used to hard-code "WAN is
  up" (only ever true because this dev host happened to be connected
  when 1.3 was written); it now measures WAN reachability independently
  from the `portal` container itself and asserts portal's reported state
  matches that measurement, whichever way it comes out — passes
  identically to before when WAN is actually up, and correctly now when
  it genuinely isn't.
- **Open self-registration on chat.island; open access on talk.island.**
  See "Matrix: chat.island" above — a deliberate lab-profile tradeoff (no
  WAN path to abuse it from), not appropriate to carry forward unexamined
  into a deployment
  that ever gains one.
- **Synapse's login/registration rate limiter can make a repeat
  `verify.sh` run slow** (`verify-matrix-e2ee.py` registers brand-new
  accounts every run). It self-heals — `matrix-nio` backs off and retries
  rather than failing — but a run can take several minutes instead of
  seconds if triggered. Not a bug, just worth knowing before assuming a
  slow run has hung.
- **talk.island's TLS is self-signed, not real PKI.** See
  `jitsi/README.md`'s "Why jitsi-gateway terminates TLS" — necessary for
  WebRTC to work in a browser at all (a browser platform restriction, not
  a choice), not a security property this repo is claiming.

## Verification performed

Ran `docker compose -f ../core/compose.yaml up -d` then
`docker compose up -d` here, on this machine (macOS + Docker Desktop,
`linux/arm64` native — CoreDNS needs no platform pin unlike the Open5GS
side). Confirmed:

- `dns` reaches `healthy`; logs show both `.:53` and `island.:53` server
  blocks loaded.
- From the UERANSIM UE (after adding the `10.46.0.0/24` route over
  `uesimtun0`): `dig +short portal.island @10.46.0.53` → `10.46.0.10`;
  same for `library.island`/`learn.island`/`maps.island` → `10.46.0.11`,
  `chat.island` → `10.46.0.20`, `talk.island` → `10.46.0.30`.
- `dig unknown.island @10.46.0.53` → `NXDOMAIN` (not `SERVFAIL` — this
  was wrong on the first pass with the `hosts` plugin; switching to a
  real zone file with the `file` plugin fixed it, see "The `.island`
  zone" above).
- `dig example.com @10.46.0.53` resolves via the forwarder (WAN is up on
  this dev host).
- Simulated WAN-down: temporarily pointed `forward` at unreachable
  addresses (`240.0.0.1`/`240.0.0.2`, Class E, never routed) — a single
  query against them returned a clean `SERVFAIL` in ~2.1s (`dig +tries=1
  +time=5`), and `portal.island` resolved correctly and fast (~0.15s) the
  whole time, unaffected. Reverted the Corefile back to the real
  resolvers afterward.
- Re-ran `../core/verify.sh` end-to-end after all of the above: still
  `ALL CHECKS PASSED`, confirming the `services_net`/NAT changes to
  `stack/core/compose.yaml` didn't regress 1.1-c/1.1-d.

**1.3-b (NOMAD):** `nomad-gateway` reaches `healthy` (after fixing its
healthcheck to hit `127.0.0.1` instead of `localhost` — this image's
`/etc/hosts` resolves `localhost` to `::1` first, and the mounted
`default.conf` is IPv4-only; see the compose file's own comment). From
the UERANSIM UE, `curl http://library.island/` → `200`, real Kiwix
landing page; `curl http://library.island/content/wikipedia_en_100_mini_
2026-01/Antarctica` → `200`, a real Wikipedia article
(`<title>Antarctica</title>`); `learn.island`/`maps.island` → `200` too
(same content, see `nomad/README.md`'s "Known limitations"). Full detail,
including the storage-mount failure this surfaced, is in
[`nomad/README.md`](nomad/README.md)'s own "Verification performed".

**1.3-c (Matrix):** Two real mistakes surfaced and got fixed before
landing:

- Mounting `config/matrix-synapse/homeserver.yaml` onto
  `/data/homeserver.yaml`, itself inside an already-mounted `/data`
  directory volume, failed outright: Docker Desktop's virtiofs backend
  refused it ("mounting ... is outside of rootfs"). Fixed by mounting the
  config directory separately at `/config` instead of layering a
  single-file mount over the directory mount.
- Assumed Element Web's nginx listens on `8080` based on inspecting the
  image with `--entrypoint sh` (bypassing `docker-entrypoint.sh`
  entirely) — the *shipped* `default.conf` does say 8080, but the real
  entrypoint's templating rewrites it to port `80` before nginx actually
  starts. `matrix-gateway`'s `proxy_pass` and the healthcheck both
  pointed at the wrong port until caught by `matrix-element` reporting
  `unhealthy` against a container whose logs showed nginx starting
  cleanly — a good reminder to check running behavior, not a bypassed
  inspection, before writing it into config.

Also verified live, since the docs don't explicitly confirm it: Synapse
merging multiple `-c` config files at real `run`-mode startup (started a
throwaway container with `-c base.yaml -c secrets.yaml` split across
`server_name` and other keys, confirmed it booted correctly using both
files' values — a `synapse.config read <key> -c a -c b` debug-subcommand
test tried first gave a misleading "key not found" result that doesn't
reflect real startup behavior).

Confirmed end-to-end, from the UERANSIM UE: `curl http://chat.island/`
→ Element Web; `curl http://chat.island/_matrix/client/versions` →
Synapse's real version list, `io.element.e2ee_forced.*: true` in its
unstable_features (confirming `encryption_enabled_by_default_for_room_type:
all` took effect). Then, with `verify-matrix-e2ee.py` (real
`matrix-nio[e2e]` crypto, not just HTTP calls):

- Two brand-new accounts registered with a single `m.login.dummy` UIA
  stage — no email/captcha, confirming
  `enable_registration_without_verification`.
- A room created by one account came back `encrypted: True` in the
  client library's own state with no explicit `m.room.encryption` event
  sent — confirming the server-side default actually fired.
- A message sent by one account was correctly decrypted by the other,
  using an independently-initialized Olm/Megolm session (separate
  `store_path`, separate device).
- The raw server-stored event, fetched over the plain client-server API
  (not through any decrypting client), had `"type": "m.room.encrypted"`
  and a `ciphertext` field — and the plaintext body was confirmed absent
  from the raw JSON entirely. This is the check that actually matters:
  an earlier draft of this test (visible in this repo's own history)
  passed its "decrypted body matches" assertion while the raw event was
  plain `m.room.message` with the plaintext sitting right there — because
  the test client's crypto store was never initialized (no `store_path`
  set), so nothing was ever actually encrypted; `nio` silently accepted
  and "decrypted" a message that had never been ciphertext. Catching that
  before it hid behind a passing test is why this file's checks fetch and
  assert on the raw server event, not just trust the client library.
- Re-ran `../core/verify.sh` end-to-end after all of the above: still
  `ALL CHECKS PASSED`, no regression.

**1.3-d (Jitsi):** full detail, including the three real mistakes fixed
before landing (a host-port collision with NOMAD, an invalid coturn CLI
flag, and the secure-context/TLS chain — the significant one), is in
[`jitsi/README.md`](jitsi/README.md)'s own "Verification performed".
Summary: `talk.island` serves a real Jitsi Meet + coturn deployment; two
headless-Chromium participants (fake audio/video devices, forced through
the JVB media path rather than
Jitsi's 2-person P2P shortcut) joined the same room and exchanged real,
live audio RTP, confirmed via each side's own `RTCPeerConnection.
getStats()` showing a non-empty inbound-rtp/audio report with non-zero
`audioLevel` and `packetsReceived` actually growing over a 5-second
window — not just "both joined". The check ran sharing the actual UE
container's network namespace (`--network container:core-ue-1`), and
incidentally proved zero WAN dependency in the process: installing the
test tooling itself inside that namespace fails outright (`ENETUNREACH`
— no WAN route exists from `core_net` at all), which is why `verify.sh`
installs into a reusable named volume from a `services_net` container
first and only runs the actual call test inside the UE's namespace.
Re-ran `../core/verify.sh` again afterward: still `ALL CHECKS PASSED`.

**1.3-e (portal):** verified the `forward`-with-loopback-fallback design
in isolation before trusting it — a standalone CoreDNS instance with two
unreachable upstreams (`240.0.0.1`/`240.0.0.2`, Class E, never routed)
plus a real one as the third, `policy sequential` entry: `dig
example.com` against it returned the loopback block's answer, not
`SERVFAIL`, confirming `forward` really does fall through to a working
upstream later in its list rather than giving up after the first
failures (~2s for the very first query, instant afterward once
`health_check` marks the dead ones — same shape as 1.3-a's own
measurements).

Then, against the real deployment, from the actual UERANSIM UE:

- WAN up (this dev host's real state): `curl http://portal.island/` →
  the live status page, `Internet (WAN) uplink: up`, all four service
  rows (`library.island`, `chat.island`, `talk.island`, local DNS)
  showing up; `curl http://portal.island/status` → the same data as
  JSON. This is what `verify.sh`'s check 8 automates.
- WAN down, simulated the same way as every other WAN-down claim in
  this repo (temporarily pointing `config/coredns/Corefile`'s `forward`
  list and `config/portal/server.py`'s `WAN_PROBE_HOST` at `240.0.0.1`
  instead of the real resolvers/`1.1.1.1`, recreating both containers,
  then reverting): `curl http://portal.island/` from the UE showed
  `Internet (WAN) uplink: down` correctly, and — the acceptance
  criterion's actual point — `dig someexternalsite.example @10.46.0.53`
  from the UE resolved to `10.46.0.10` (portal's own address) instead of
  `SERVFAIL`, confirming the resolve-anything fallback works for a UE
  exactly the way it did for the isolated test above. Reverted both
  files to the real configuration afterward (verified via `diff` against
  a saved copy — both came back byte-identical) and re-ran
  `../core/verify.sh`: still `ALL CHECKS PASSED`.

**1.3-f (one-command island):** tested `island.sh` against a genuinely
empty state, not just a re-run on top of an already-configured host —
every `.env`/secrets/cert file moved aside, every relevant compose
project torn down including volumes, the out-of-band `nomad_kiwix_server`
container removed. `./island.sh up` from there surfaced two real bugs,
both fixed before landing:

- **A genuine ordering bug, previously masked.** The very first clean
  run failed with `nomad-gateway` never becoming healthy. Root cause:
  `nomad-gateway`'s healthcheck proxies through to Kiwix, so it can never
  pass until Kiwix exists — but every earlier dev-session test in this
  repo had a Kiwix container already running, left over from a previous
  task's testing, so this ordering dependency never actually got
  exercised until now. Fixed by moving NOMAD's own bring-up (and the
  Kiwix install) before `stack/services`' in `island.sh`'s `up` — see
  its own comment on this.
- **A stale-credential mismatch, purely a testing artifact but worth
  recording.** After the above fix, NOMAD's admin and Synapse both
  crash-looped on database auth failures. Cause: their Postgres/MySQL
  data volumes had persisted from earlier sessions with the *old*
  passwords, while freshly deleting only the `.env`/secrets files (not
  the data volumes) made `island.sh` generate *new* random passwords —
  a real mismatch, but one that can only happen by deleting secrets
  without also clearing the data they protect, not on an actual fresh
  host. Removing the stale volumes (and Jitsi's `data/` directory, which
  hit the identical class of problem with prosody's stored jicofo/jvb
  credentials) resolved it. Documented here rather than silently
  worked around, since it's a real trap for anyone regenerating secrets
  on a host that already has data.

With both fixed, ran the full scenario end-to-end multiple times from
a clean state: `island.sh up` → `stack/services/verify.sh` → all 8
checks pass (UE registers, resolves and browses `library.island`,
exchanges a real E2EE Matrix message, holds a real audio call, gets
correct live portal status) → `island.sh down` tears everything back
down cleanly → `island.sh up` again (now idempotent, nothing to
bootstrap) brings it all back. `island.sh status` reports per-component
container health plus a host-level WAN reachability check.
