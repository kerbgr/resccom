"""Sync the local subscriber store into Open5GS's MongoDB (WBS 3.2-b/3.2-e).

This is the one implementation of "what a subscriber document looks like
in Open5GS's `subscribers` collection" and "how to run a script against
the core's `mongo` container" -- it replaces
`stack/core/load-subscribers.py`, which did the same
docker-compose-exec-mongosh thing but only ever upserted, never
reconciled deletions. See sim-tools/README.md and
stack/core/README.md's "Scripted path" section.

`db sync` is a full reconcile, not an upsert-only push: the local store is
authoritative, so any subscriber document in Mongo whose IMSI is not in
the local store gets deleted. That's what makes "remove locally, then
sync" actually revoke core access instead of just leaving a stale
document behind.

WBS 3.2-e: a subscriber whose would-be document is identical to what's
already in Mongo (ignoring generated `_id`/ObjectId fields) is left
untouched rather than `replaceOne`'d. A `replaceOne` is a real write even
when the values don't change, and Open5GS's UDR treats any write to a
subscriber document as a subscription-data change -- for a UE with an
active PDU session that tears down routing the AMF/SMF/UPF can't silently
recover from (see stack/ran/README.md's 5G-alt writeup). Skipping the
no-op write is what lets multiple rigs share one store and repeatedly
`db sync` it without disturbing each other's live sessions.

The comparison also ignores a handful of fields Open5GS itself writes
back into a subscriber's document as part of normal operation, not just
generated `_id`s: `imeisv` (the device identity reported at 5GMM/EMM
Identity, overwriting our provisioned `[]` with a bare string) and
`security.sqn` (the persisted AKA sequence-number state, absent until the
first successful authentication). `mme_host`/`mm_realm`/`purge_flag` are
the same kind of thing on the 4G/HSS side. Found live, not by inspection:
running this rig's own multi-rig scenario reproduced this repo's original
3.2-e bug in a NEW way -- an already-attached UE's subscriber document had
picked up its `sqn`/`imeisv` since attach, so a same-content-looking
`db sync` still saw a real diff, still called `replaceOne`, and still
broke that UE's PDU session, exactly like an unconditional replaceOne
would have. Treating these as ours-to-ignore, not ours-to-manage, is what
makes the skip in the previous paragraph actually hold for a subscriber
that has genuinely attached since it was last synced.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .model import Subscriber

DEFAULT_APN = "internet"
DEFAULT_SST = 1
# 3.3-c v2h: named, not inlined, so roaming.py's policy-only inbound-roamer
# documents (a *different* Mongo, at the visited island) use the exact same
# QoS/AMBR a home-provisioned subscriber gets -- no drift between what a
# subscriber's policy looks like at home vs. what a visited island's PCF
# applies to their roaming session.
DEFAULT_QOS_INDEX = 9
DEFAULT_ARP_PRIORITY = 8
DEFAULT_ARP_PREEMPT_CAP = 1
DEFAULT_ARP_PREEMPT_VULN = 2
DEFAULT_AMBR_VALUE = 1_000_000_000
DEFAULT_AMBR_UNIT = 0


class SyncError(Exception):
    """`docker compose exec` or `mongosh` failed; message is user-facing."""


@dataclass(frozen=True, slots=True)
class SyncResult:
    added: int
    updated: int
    unchanged: int
    removed: int


# Deep-compares two documents for equality while ignoring:
# - any `_id` field (Mongo/BSON ObjectIds, generated fresh on every
#   potential write), and
# - fields Open5GS itself writes back into a subscriber's document as part
#   of normal operation, not just what resccom-sim provisioned: `imeisv`
#   (the device identity reported at 5GMM/EMM Identity), `security.sqn`
#   (persisted AKA sequence-number state), and `mme_host`/`mm_realm`/
#   `purge_flag` (the 4G/HSS equivalent). A subscriber that's genuinely
#   attached since the last sync will have picked these up -- comparing
#   them would make an unattached-looking, content-identical subscriber
#   look "changed" and trigger exactly the no-op-but-still-a-write
#   `replaceOne` this comparison exists to avoid (found live -- see this
#   module's docstring).
# Also normalizes BSON numeric wrapper types (e.g. `NumberInt`, which
# mongosh returns as a wrapper object on read-back, not a bare JS number)
# down to their primitive value before comparing.
_CANON_JS = """
const IGNORED_KEYS = new Set(["_id", "imeisv", "sqn", "mme_host", "mm_realm", "purge_flag"]);
function normalize(v) {
  if (v === null || v === undefined) return v;
  if (Array.isArray(v)) return v.map(normalize);
  if (typeof v === "object") {
    if (typeof v.valueOf === "function") {
      const prim = v.valueOf();
      if (typeof prim !== "object") return prim;
    }
    const out = {};
    for (const k of Object.keys(v)) {
      if (IGNORED_KEYS.has(k)) continue;
      out[k] = normalize(v[k]);
    }
    return out;
  }
  return v;
}
function canon(v) {
  v = normalize(v);
  if (v === null || v === undefined) return "null";
  if (Array.isArray(v)) return "[" + v.map(canon).join(",") + "]";
  if (typeof v === "object") {
    return "{" + Object.keys(v).sort().map(k => JSON.stringify(k) + ":" + canon(v[k])).join(",") + "}";
  }
  return JSON.stringify(v);
}
""".strip()


def slice_js(lbo_roaming_allowed: bool) -> str:
    """The `"slice": [...]` field, shared by a full local subscriber document
    (`_doc_js`) and roaming.py's policy-only inbound-roamer document -- the
    *only* part of a subscriber document Open5GS's PCF reads for SM Policy
    Association (`lib/dbi/session.c` `ogs_dbi_session_data()`, TASKS.md
    3.3-c v2g review). Never includes `security` -- that key doesn't exist
    in this fragment at all, by construction.
    """
    return f"""[
      {{
        "sst": NumberInt({DEFAULT_SST}),
        "default_indicator": true,
        "session": [
          {{
            "name": "{DEFAULT_APN}",
            "type": NumberInt(3),
            "qos": {{
              "index": NumberInt({DEFAULT_QOS_INDEX}),
              "arp": {{
                "priority_level": NumberInt({DEFAULT_ARP_PRIORITY}),
                "pre_emption_capability": NumberInt({DEFAULT_ARP_PREEMPT_CAP}),
                "pre_emption_vulnerability": NumberInt({DEFAULT_ARP_PREEMPT_VULN})
              }}
            }},
            "ambr": {{
              "downlink": {{ "value": NumberInt({DEFAULT_AMBR_VALUE}), "unit": NumberInt({DEFAULT_AMBR_UNIT}) }},
              "uplink": {{ "value": NumberInt({DEFAULT_AMBR_VALUE}), "unit": NumberInt({DEFAULT_AMBR_UNIT}) }}
            }},
            "lbo_roaming_allowed": {"true" if lbo_roaming_allowed else "false"},
            "pcc_rule": [],
            "_id": new ObjectId()
          }}
        ],
        "_id": new ObjectId()
      }}
    ]""".strip()


def _doc_js(sub: Subscriber) -> str:
    # Same document shape as stack/core/load-subscribers.py mirrored from
    # upstream's own misc/db/open5gs-dbctl "add" command (same open5gs
    # image tag pinned in stack/core/README.md "Versions").
    return f"""{{
    "schema_version": NumberInt(1),
    "imsi": "{sub.imsi}",
    "msisdn": [], "imeisv": [], "mme_host": [], "mm_realm": [], "purge_flag": [],
    "slice": {slice_js(sub.lbo_roaming_allowed)},
    "security": {{ "k": "{sub.key.upper()}", "op": null, "opc": "{sub.opc.upper()}", "amf": "{sub.amf.upper()}" }},
    "ambr": {{
      "downlink": {{ "value": NumberInt({DEFAULT_AMBR_VALUE}), "unit": NumberInt({DEFAULT_AMBR_UNIT}) }},
      "uplink": {{ "value": NumberInt({DEFAULT_AMBR_VALUE}), "unit": NumberInt({DEFAULT_AMBR_UNIT}) }}
    }},
    "access_restriction_data": 32,
    "network_access_mode": 0,
    "subscriber_status": 0,
    "operator_determined_barring": 0,
    "subscribed_rau_tau_timer": 12,
    "__v": 0
  }}""".strip()


def sync_script(subscribers: list[Subscriber]) -> str:
    """The mongosh script that makes Mongo match `subscribers` exactly.

    For each subscriber: inserts it if missing, leaves it alone if an
    identical document is already there, and `replaceOne`s it only if it's
    actually different. Then deletes any Mongo document whose IMSI isn't in
    `subscribers`. Prints one JSON summary line (added/updated/
    unchanged/removed counts) that `run_sync` parses.
    """
    imsi_list = ", ".join(f'"{s.imsi}"' for s in subscribers)
    entries = ",\n    ".join(f'{{ imsi: "{s.imsi}", doc: {_doc_js(s)} }}' for s in subscribers)
    return f"""
{_CANON_JS}
const subs = [
    {entries}
];
let added = 0, updated = 0, unchanged = 0;
for (const sub of subs) {{
  const existing = db.subscribers.findOne({{ imsi: sub.imsi }});
  // 3.3-c v2h: an inbound-roamer record (roaming.py's `roaming import`,
  // marked resccom_inbound_roamer:true) belongs to a *different* island's
  // local store than this one -- a local `db sync` never upserts over it,
  // even if its IMSI happens to also appear in this island's own store.
  if (existing && existing.resccom_inbound_roamer === true) {{
    continue;
  }}
  if (!existing) {{
    db.subscribers.insertOne(sub.doc);
    added++;
  }} else if (canon(existing) === canon(sub.doc)) {{
    unchanged++;
  }} else {{
    db.subscribers.replaceOne({{ imsi: sub.imsi }}, sub.doc);
    updated++;
  }}
}}
// 3.3-c v2h: the reconcile-delete only ever removes documents this local
// store is authoritative over -- an inbound-roamer record's authority is
// the *home* island's store, not this one, so it's excluded even when its
// IMSI isn't (and never will be) in this island's own subscriber list.
const removed = db.subscribers.deleteMany({{
  imsi: {{ $nin: [{imsi_list}] }},
  resccom_inbound_roamer: {{ $ne: true }}
}}).deletedCount;
print(JSON.stringify({{ added: added, updated: updated, unchanged: unchanged, removed: removed }}));
""".strip()


def run_sync(subscribers: list[Subscriber], core_dir: Path) -> SyncResult:
    """Runs sync_script() against core_dir's `mongo` compose service.

    Returns a SyncResult parsed from mongosh's stdout on success. Raises
    SyncError (docker compose missing, mongo not running, script error,
    unparseable output, ...) otherwise.
    """
    result = subprocess.run(
        [
            "docker", "compose", "exec", "-T", "mongo",
            "mongosh", "--quiet", "mongodb://localhost/open5gs",
            "--eval", sync_script(subscribers),
        ],
        cwd=core_dir,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise SyncError(f"mongosh failed:\n{result.stdout}\n{result.stderr}")
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    if not lines:
        raise SyncError(f"mongosh produced no output:\n{result.stderr}")
    try:
        summary = json.loads(lines[-1])
        return SyncResult(**summary)
    except (ValueError, TypeError) as exc:
        raise SyncError(f"could not parse mongosh output:\n{result.stdout}") from exc
