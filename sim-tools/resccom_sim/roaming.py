"""Inbound-roamer policy records between islands (WBS 3.3-c v2h).

TASKS.md 3.3-c v2g's review traced Local Breakout's last blocker to source:
Open5GS's PCF answers SM Policy Association from its *own* island's local
MongoDB (`pcf.yaml.j2`'s `db_uri`), reading only a subscriber's
`slice[].session[]` policy (`lib/dbi/session.c` `ogs_dbi_session_data()`) --
never the `security` block (K/OPc/AMF). A roaming subscriber's document lives
only at their home island (RFC-0003 D1), so a visited island's PCF has
nothing to find for them and rejects the PDU session with a real 404.

This module is the fix RFC-0003 D1 was amended to describe: the home island
exports a roaming-enabled subscriber's *policy only* -- no security anywhere,
by construction, not by filtering -- and the visited island imports it as a
document marked `resccom_inbound_roamer: true` / `home_plmn: {mcc, mnc}`, so
`db sync` (sync.py) can tell it apart from that island's own subscribers and
never touch it. This is exactly what a visited PCF holds under a real 3GPP
roaming agreement (the visited operator's own policy applied to the roamer's
session) -- not D3's guest provisioning (a full credentialed local
subscriber), and not an attempt to work around Open5GS's missing N24
(Npcf, V-PCF<->H-PCF) interface, which this project cannot patch (CLAUDE.md).

**Upstream shared-DB caveat**: Open5GS's own roaming examples
(`configs/examples/5gc-no-scp-sepp{1,2,3}-*.yaml.in`) never hit this gap
because all three islands in that example point `db_uri` at the *same*
MongoDB (`mongodb://localhost/open5gs`) -- every PCF in the example finds
every SUPI because there is only one database. Two real islands, each with
their own Mongo (this project's actual model), need policy data to actually
travel; this module is that travel, exporting the minimum a visited PCF
needs and nothing else.

Transport is out of scope here (WBS 3.3-c v2h step 1): the export file is
handed over by an operator, unsigned, the same way `two-island.sh`'s own
harness copies it between the two checkouts it manages -- a lab-only
shortcut (SECURITY.md's lab-profile register). Signing and exchange over the
overlay belong with WBS 3.4 (PKI).
"""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .model import IMSI_RE, Subscriber
from .sync import slice_js

# Any of these, anywhere in an imported record's top level, means it carries
# (or claims to carry) credential material -- refused outright, not
# stripped. "K never leaves home" is enforced here, in code, not left to
# whoever writes the export file to get right.
CREDENTIAL_LIKE_KEYS = {"security", "k", "opc", "op", "amf"}

MCC_RE = re.compile(r"^\d{3}$")
MNC_RE = re.compile(r"^\d{2,3}$")


class RoamingExportError(Exception):
    """An export request named an IMSI the store doesn't have."""


class RoamingImportError(Exception):
    """A record failed import -- credentialed, malformed, conflicting, or mongosh failed."""


@dataclass(frozen=True, slots=True)
class PolicyRecord:
    """A roaming-enabled subscriber's policy, and nothing else.

    No `key`, no `opc`, no `amf` -- unlike `model.Subscriber`, this type
    cannot represent credential material at all, so there is no field to
    accidentally serialize.
    """

    imsi: str
    lbo_roaming_allowed: bool

    def to_dict(self) -> dict:
        return {"imsi": self.imsi, "lbo_roaming_allowed": self.lbo_roaming_allowed}


def export_policy_records(subscribers: list[Subscriber], imsis: list[str] | None = None) -> list[PolicyRecord]:
    """Selects which subscribers to export.

    Default (`imsis=None`): every subscriber with `lbo_roaming_allowed`
    true -- a Home-Routed subscriber never roams via Local Breakout, so
    there is nothing for a visited PCF to need for them. `imsis` narrows to
    exactly those IMSIs, erroring if any is missing from the store or is
    Home-Routed (an explicit ask should not silently export nothing).
    """
    by_imsi = {s.imsi: s for s in subscribers}
    if imsis is None:
        return [
            PolicyRecord(imsi=s.imsi, lbo_roaming_allowed=s.lbo_roaming_allowed)
            for s in subscribers
            if s.lbo_roaming_allowed
        ]
    records = []
    for imsi in imsis:
        sub = by_imsi.get(imsi)
        if sub is None:
            raise RoamingExportError(f"no such subscriber: {imsi}")
        if not sub.lbo_roaming_allowed:
            raise RoamingExportError(f"{imsi} is Home-Routed (lbo_roaming_allowed=false) -- nothing to export")
        records.append(PolicyRecord(imsi=sub.imsi, lbo_roaming_allowed=sub.lbo_roaming_allowed))
    return records


def write_export_file(records: list[PolicyRecord], out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"records": [r.to_dict() for r in records]}, indent=2) + "\n")


def _validate_record(raw: dict) -> PolicyRecord:
    present = CREDENTIAL_LIKE_KEYS & {str(k).lower() for k in raw}
    if present:
        raise RoamingImportError(
            f"refusing record {raw.get('imsi', '?')}: carries a credential-like field "
            f"{sorted(present)} -- K never leaves home, this import path is policy-only"
        )
    imsi = raw.get("imsi")
    if not imsi or not IMSI_RE.match(str(imsi)):
        raise RoamingImportError(f"record has no valid 15-digit imsi: {raw!r}")
    return PolicyRecord(imsi=str(imsi), lbo_roaming_allowed=bool(raw.get("lbo_roaming_allowed", True)))


def read_import_file(path: Path) -> list[PolicyRecord]:
    data = json.loads(path.read_text())
    raw_records = data["records"] if isinstance(data, dict) else data
    return [_validate_record(r) for r in raw_records]


def _inbound_doc_js(record: PolicyRecord, home_mcc: str, home_mnc: str) -> str:
    # Deliberately NOT `_doc_js` (sync.py): no `security`, no `msisdn`/
    # `imeisv`/`mme_host`/`mm_realm`/`purge_flag` -- those are this
    # subscriber's home-island identity fields, not this island's to hold.
    # `slice_js` is the exact fragment PCF's own SM-Policy lookup reads
    # (sync.py's module docstring / TASKS.md 3.3-c v2g review), shared with
    # a full local document so a roamer's policy matches what they'd get
    # from their own home island's PCF.
    return f"""{{
    "schema_version": NumberInt(1),
    "imsi": "{record.imsi}",
    "resccom_inbound_roamer": true,
    "home_plmn": {{ "mcc": "{home_mcc}", "mnc": "{home_mnc}" }},
    "slice": {slice_js(record.lbo_roaming_allowed)},
    "access_restriction_data": 32,
    "network_access_mode": 0,
    "subscriber_status": 0,
    "operator_determined_barring": 0,
    "subscribed_rau_tau_timer": 12,
    "__v": 0
  }}""".strip()


@dataclass(frozen=True, slots=True)
class ImportResult:
    imported: int
    conflicts: tuple[str, ...]


def _import_script(records: list[PolicyRecord], home_mcc: str, home_mnc: str) -> str:
    entries = ",\n    ".join(
        f'{{ imsi: "{r.imsi}", doc: {_inbound_doc_js(r, home_mcc, home_mnc)} }}' for r in records
    )
    return f"""
const recs = [
    {entries}
];
let imported = 0;
const conflicts = [];
for (const rec of recs) {{
  const existing = db.subscribers.findOne({{ imsi: rec.imsi }});
  // Never overwrite a document this island's own db sync owns (an
  // unmarked, real local subscriber) -- only an absent document or an
  // existing inbound-roamer record (re-import, e.g. a refreshed export)
  // may be written here.
  if (existing && existing.resccom_inbound_roamer !== true) {{
    conflicts.push(rec.imsi);
    continue;
  }}
  db.subscribers.replaceOne({{ imsi: rec.imsi }}, rec.doc, {{ upsert: true }});
  imported++;
}}
print(JSON.stringify({{ imported: imported, conflicts: conflicts }}));
""".strip()


def run_import(records: list[PolicyRecord], core_dir: Path, *, home_mcc: str, home_mnc: str) -> ImportResult:
    """Upserts `records` into `core_dir`'s Mongo, marked as inbound roamers.

    Raises RoamingImportError if any record's IMSI already exists as an
    unmarked (real local) subscriber at this island -- an inbound-roamer
    import never overwrites a genuine local subscriber, marked or not.
    """
    if not MCC_RE.match(home_mcc) or not MNC_RE.match(home_mnc):
        raise RoamingImportError(f"invalid --home-plmn {home_mcc}/{home_mnc}: want 3-digit MCC, 2-3-digit MNC")
    result = subprocess.run(
        [
            "docker", "compose", "exec", "-T", "mongo",
            "mongosh", "--quiet", "mongodb://localhost/open5gs",
            "--eval", _import_script(records, home_mcc, home_mnc),
        ],
        cwd=core_dir,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RoamingImportError(f"mongosh failed:\n{result.stdout}\n{result.stderr}")
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    if not lines:
        raise RoamingImportError(f"mongosh produced no output:\n{result.stderr}")
    try:
        summary = json.loads(lines[-1])
    except (ValueError, TypeError) as exc:
        raise RoamingImportError(f"could not parse mongosh output:\n{result.stdout}") from exc
    conflicts = tuple(summary.get("conflicts", []))
    if conflicts:
        raise RoamingImportError(
            "refusing to overwrite existing local subscriber(s) with an inbound-roamer "
            f"record: {', '.join(conflicts)}"
        )
    return ImportResult(imported=summary["imported"], conflicts=conflicts)


def run_list(core_dir: Path) -> list[dict]:
    """Lists inbound-roamer records currently held at `core_dir`'s island."""
    script = (
        "print(JSON.stringify(db.subscribers.find("
        '{ resccom_inbound_roamer: true }, { imsi: 1, home_plmn: 1, _id: 0 }'
        ").toArray()))"
    )
    result = subprocess.run(
        ["docker", "compose", "exec", "-T", "mongo", "mongosh", "--quiet", "mongodb://localhost/open5gs", "--eval", script],
        cwd=core_dir,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RoamingImportError(f"mongosh failed:\n{result.stdout}\n{result.stderr}")
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    if not lines:
        raise RoamingImportError(f"mongosh produced no output:\n{result.stderr}")
    try:
        return json.loads(lines[-1])
    except (ValueError, TypeError) as exc:
        raise RoamingImportError(f"could not parse mongosh output:\n{result.stdout}") from exc


def run_remove(imsi: str, core_dir: Path) -> bool:
    """Removes one inbound-roamer record by IMSI. Never touches an unmarked document."""
    script = (
        "print(JSON.stringify({ deleted: db.subscribers.deleteOne("
        f'{{ imsi: "{imsi}", resccom_inbound_roamer: true }}).deletedCount }}))'
    )
    result = subprocess.run(
        ["docker", "compose", "exec", "-T", "mongo", "mongosh", "--quiet", "mongodb://localhost/open5gs", "--eval", script],
        cwd=core_dir,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RoamingImportError(f"mongosh failed:\n{result.stdout}\n{result.stderr}")
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    if not lines:
        raise RoamingImportError(f"mongosh produced no output:\n{result.stderr}")
    try:
        summary = json.loads(lines[-1])
    except (ValueError, TypeError) as exc:
        raise RoamingImportError(f"could not parse mongosh output:\n{result.stdout}") from exc
    return bool(summary.get("deleted", 0))
