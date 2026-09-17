"""island-init apply (2.1-f): the host-side half of the Island Console's
Apply flow (RFC-0006 D5).

The console (stack/services/config/console/server.py) only ever edits and
validates a *draft* -- an unsigned candidate document written to disk once
it passes schema + semantic checks. Signing and rendering happen here,
run on the host by an operator (`island.sh apply`) or a future host-only
agent, never inside the console container: the private signing key and
the `docker restart` calls this needs must never be reachable from
anything the UE subnet can talk to (SECURITY.md's lab-profile register
row on `console.island`, tightened by this task).

`build_candidate`/`LOCKED_ISLAND_FIELDS` are shared with server.py (not
duplicated) so a draft staged by the console and a candidate built here
lock the same identity fields the same way.
"""
from __future__ import annotations

import base64
import copy
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from .checks import run_semantic_checks
from .crypto import SigningKeypair, sign_document
from .render import RenderError, render_all, write_all
from .schema import validate_schema
from .yaml_io import dump, load

# Kept at the same path 2.1-d's console used for its own apply log, so a
# node upgraded from 2.1-d to 2.1-f sees one continuous history rather
# than a second file starting from zero.
APPLY_LOG_RELATIVE = "stack/services/data/console/console-apply.log"

# render target -> (docker-compose project, service) -- container name is
# "<project>-<service>-1", docker compose's own default naming when a
# compose file has no explicit `name:` (confirmed against this repo's
# running containers). lis-geometry.json has no running consumer to
# restart.
RESTART_MAP: dict[str, tuple[str, str]] = {
    "stack/core/config/amf.yaml": ("core", "amf"),
    "stack/core/config/mme.yaml": ("core", "mme"),
    "stack/core/config/nrf.yaml": ("core", "nrf"),
    "stack/core/config/smf.yaml": ("core", "smf"),
    "stack/core/config/upf.yaml": ("core", "upf"),
    "stack/core/config/freeDiameter/hss.conf": ("core", "hss"),
    "stack/core/config/freeDiameter/mme.conf": ("core", "mme"),
    "stack/core/config/freeDiameter/pcrf.conf": ("core", "pcrf"),
    "stack/core/config/freeDiameter/smf.conf": ("core", "smf"),
    "stack/services/config/coredns/island.zone": ("services", "dns"),
    "stack/services/data/portal/settings.json": ("services", "portal"),
    "stack/backhaul/config/uplinks.yaml": ("backhaul", "wan-edge"),
}

# Identity fields no edit -- draft or otherwise -- is allowed to change;
# they're generated once (island-init new) and only ever re-derived from
# what's already on disk, never from a posted candidate.
LOCKED_ISLAND_FIELDS = ("id", "signing_key_fingerprint", "signing_public_key")


class ApplyError(Exception):
    pass


def _plain(data) -> dict:
    """Strips ruamel's CommentedMap/CommentedSeq wrappers via a JSON
    round-trip -- `yaml_io.load`'s round-trip loader always returns those
    (even for a plainly-written file), and the plain "safe" dumper
    `yaml_io.dump` uses can't represent them (same reasoning as
    `wizard._plain` / `server.load_current`)."""
    return json.loads(json.dumps(data))


def build_candidate(current: dict, posted: dict) -> dict:
    """Merges a posted/staged document onto the current one, then re-locks
    the identity fields no edit is allowed to touch."""
    candidate = copy.deepcopy(posted)
    candidate.pop("signature", None)
    for field in LOCKED_ISLAND_FIELDS:
        candidate.setdefault("island", {})[field] = current["island"].get(field)
    candidate.setdefault("island", {}).setdefault("overlay", {})["wireguard_public_key"] = (
        current["island"].get("overlay", {}).get("wireguard_public_key")
    )
    return candidate


def validate(candidate: dict) -> list:
    issues = validate_schema(candidate)
    if not issues:
        issues = run_semantic_checks(candidate, candidate)
    return issues


def load_signing_keypair(current: dict, secrets_dir: Path) -> SigningKeypair:
    island_id = current["island"]["id"]
    key_path = secrets_dir / island_id / "signing.key"
    if not key_path.exists():
        raise ApplyError(f"{key_path} not found -- run island-init new to generate a signing key")
    private_raw = base64.b64decode(key_path.read_text(encoding="utf-8").strip())
    private_key = Ed25519PrivateKey.from_private_bytes(private_raw)
    return SigningKeypair(
        private_key=private_key,
        public_key_b64=current["island"]["signing_public_key"],
        fingerprint=current["island"]["signing_key_fingerprint"],
    )


def restart_for(changed_paths: list[str]) -> list[str]:
    """Restarts the containers of every changed file that has a running
    consumer (RESTART_MAP) -- run on the host, where `docker` is just
    another command on PATH, not a socket handed to an untrusted
    container."""
    restarted: list[str] = []
    for path in changed_paths:
        target = RESTART_MAP.get(path)
        if target is None:
            continue
        project, service = target
        container = f"{project}-{service}-1"
        if container in restarted:
            continue
        try:
            subprocess.run(["docker", "restart", container], check=True, capture_output=True, timeout=60)
            restarted.append(container)
        except FileNotFoundError as exc:
            raise ApplyError("docker not found on PATH -- island-init apply must run on the node host") from exc
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            raise ApplyError(f"failed to restart {container}: {exc}") from exc
    return restarted


def log_apply(repo_root: Path, changed_paths: list[str], restarted: list[str]) -> None:
    """Best-effort: island.yaml is already written and services already
    restarted by the time this runs, so a logging failure must not turn
    an otherwise-successful apply into an error (2.1-d's own reasoning,
    kept through the 2.1-f host-side split)."""
    path = repo_root / APPLY_LOG_RELATIVE
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "changed_files": changed_paths,
            "restarted_containers": restarted,
        }
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError as exc:
        sys.stderr.write(f"log_apply: failed to write {path}: {exc}\n")


def apply_draft(draft_path: Path, island_yaml_path: Path, secrets_dir: Path, repo_root: Path) -> dict:
    """Loads the draft the console staged, re-validates it (defense in
    depth -- the console already validated before staging), signs it with
    the host-only key, renders, writes island.yaml + every changed
    target, restarts affected services, and clears the draft on success.

    Returns {"changed": [...], "restarted": [...]}` on success; raises
    ApplyError (with `.issues` set to a list[Issue] when validation is
    what failed) otherwise. Never leaves island.yaml or any rendered file
    partially written: validation and signing happen before anything on
    disk changes.
    """
    if not draft_path.exists():
        raise ApplyError(f"{draft_path} does not exist -- no pending draft to apply")
    if not island_yaml_path.exists():
        raise ApplyError(f"{island_yaml_path} does not exist -- run island-init new first")

    current = _plain(load(island_yaml_path))
    draft = _plain(load(draft_path))
    candidate = build_candidate(current, draft)

    issues = validate(candidate)
    if issues:
        err = ApplyError("draft failed validation:\n" + "\n".join(i.render(str(draft_path)) for i in issues))
        err.issues = issues  # type: ignore[attr-defined]
        raise err

    keypair = load_signing_keypair(current, secrets_dir)
    candidate["signature"] = sign_document(candidate, keypair)

    try:
        files = render_all(candidate, repo_root)
    except RenderError as exc:
        raise ApplyError(f"render failed: {exc}") from exc

    dump(candidate, island_yaml_path)
    written = write_all(files, repo_root)
    changed_paths = [f.path for f in written]
    restarted = restart_for(changed_paths)
    log_apply(repo_root, changed_paths, restarted)

    draft_path.unlink(missing_ok=True)

    return {"changed": changed_paths, "restarted": restarted}
