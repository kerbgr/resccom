"""ResCCOM 3.3-b follow-up 1 — two-island harness setup.

Builds real, signed island identities for A (this checkout) and B (a
second checkout), cross-populates federation.peers[] in *transient*
copies (never the committed island.example*.yaml fixtures), and renders
both trees. Called by ./two-island.sh; not meant to be run standalone
outside that wrapper's env/PATH setup.

Deliberately goes through the real `island-init` CLI (subprocess, not a
direct import) for every schema-sensitive step -- new/check/render --
same discipline island.sh itself follows ("runs the pipx-installed
island-init, not this checkout's source"), so this harness exercises
exactly the commands an operator would run, including the checks added
in follow-ups 4 and 5. Only the "read both identities and build a peered
copy" step needs direct YAML access, since no CLI command does that.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

# island_init itself is only needed for that one step -- imported from
# whichever checkout this script lives in (A's), which is also where B
# was cloned from, so both share the same module version.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "island-init"))
from island_init.crypto import sign_document, signing_keypair_from_private_b64  # noqa: E402
from island_init.yaml_io import dump, load  # noqa: E402

# Lab-only: both islands run on one Docker host, so a peer's endpoint is
# reached over compose.wan.yaml's own dedicated bridge (10.200.0.0/24),
# not the host itself -- two-island.sh creates that network and gives
# each side's wg-overlay a static address on it (WAN_NET_NAME/WG_WAN_IP)
# before this script runs. Found live (3.3-c v2e review): the earlier
# host.docker.internal mapping reached a peer through Docker Desktop's
# own *published host port*, whose NAT hairpin rewrote each peer's
# authenticated packets' source address to look like the receiver's own
# services_net gateway -- WireGuard's own endpoint-roaming then
# overwrote each peer's *configured* endpoint with that dead address, on
# BOTH peers at once, black-holing the overlay before SEPP's N32 could
# ever complete. A static wan_net address is never NAT-hairpinned, so
# there is no wrong source address for endpoint-roaming to learn. A real
# deployment's island.yaml would carry a real routable WAN endpoint
# instead (island.sh doesn't add either mapping).
A_WAN_IP = "10.200.0.2"
B_WAN_IP = "10.200.0.3"
# WireGuard's IANA-registered default port -- the container-internal
# listen port (island_init.render.WG_LISTEN_PORT) stays this fixed value
# regardless of which *host* port each side's compose.yaml separately
# publishes (that publish exists for reaching a container from outside
# Docker, e.g. a real deployment or manual poking -- irrelevant to
# peer-to-peer traffic once peers reach each other directly over
# wan_net).
WG_LISTEN_PORT = 51820


def run(cmd: list[str]) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        sys.stderr.write(result.stdout)
        sys.stderr.write(result.stderr)
        raise SystemExit(f"command failed ({result.returncode}): {' '.join(cmd)}")


def ensure_identity(repo_root: Path, *, file_source: Path | None) -> None:
    """Ensures <repo_root>/island-init/island.yaml exists and passes
    `check` -- generates it with `new --lab` (A) or `new --file` (B,
    3.3-b follow-up 1) if missing, migrates it if it's stale (follow-up
    5), and refuses to proceed if it still doesn't check out."""
    island_yaml = repo_root / "island-init" / "island.yaml"
    if not island_yaml.exists():
        if file_source is None:
            run(["island-init", "new", "--lab", "--repo-root", str(repo_root)])
        else:
            run(["island-init", "new", "--file", str(file_source), "--repo-root", str(repo_root)])

    check = subprocess.run(
        ["island-init", "check", str(island_yaml), "--repo-root", str(repo_root)],
        capture_output=True, text=True,
    )
    if check.returncode != 0:
        print(f"{island_yaml} failed check -- attempting 'island-init migrate':", file=sys.stderr)
        print(check.stdout + check.stderr, file=sys.stderr)
        run(["island-init", "migrate", str(island_yaml), "--repo-root", str(repo_root)])
        run(["island-init", "check", str(island_yaml), "--repo-root", str(repo_root)])


def load_plain(path: Path):
    return json.loads(json.dumps(load(path)))


def build_peered_copy(own: dict, peer: dict, peer_wan_ip: str) -> dict:
    data = json.loads(json.dumps(own))
    data["federation"]["peers"] = [
        {
            "name": peer["island"]["id"],
            "endpoint": f"{peer_wan_ip}:{WG_LISTEN_PORT}",
            "public_key": peer["island"]["overlay"]["wireguard_public_key"],
            "node_internal_base": peer["node"]["internal_base"],
            "services_prefix": peer["allocations"]["services_prefix"],
            # 3.3-c v2 (RFC-0003 D1 amendment): SEPP/N32 roaming needs
            # the peer's PLMN too -- AMF's own access_control and this
            # island's SEPP N32 client table both render from it.
            "plmn": peer["allocations"]["plmn"],
        }
    ]
    return data


def resign_if_needed(data: dict, secrets_dir: Path) -> dict:
    if not data.get("signature"):
        return data
    island_id = data["island"]["id"]
    fingerprint = data["island"]["signing_key_fingerprint"]
    key_path = secrets_dir / island_id / "signing.key"
    signing = signing_keypair_from_private_b64(key_path.read_text(encoding="utf-8").strip())
    if signing.fingerprint != fingerprint:
        raise SystemExit(f"{key_path} does not match {island_id}'s declared signing_key_fingerprint -- cannot re-sign")
    data["signature"] = sign_document(data, signing)
    return data


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit(f"usage: {sys.argv[0]} <a_repo_root> <b_repo_root>")
    a_dir, b_dir = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()

    ensure_identity(a_dir, file_source=None)
    ensure_identity(b_dir, file_source=a_dir / "island-init" / "island.example.b.yaml")

    a_data = load_plain(a_dir / "island-init" / "island.yaml")
    b_data = load_plain(b_dir / "island-init" / "island.yaml")

    a_peered_data = build_peered_copy(a_data, b_data, B_WAN_IP)
    b_peered_data = build_peered_copy(b_data, a_data, A_WAN_IP)

    # 3.3-c v2g: TWO_ISLAND_LOG_LEVEL (set by two-island.sh's own
    # --log-level, empty otherwise) overrides node.log_level on BOTH
    # islands' *transient* peered copies only -- never island.example*.yaml
    # or either island's own tracked island-init/island.yaml. Applied
    # after build_peered_copy (a plain dict copy of the real identity), so
    # a --log-level run and a plain run diverge only in this one field.
    log_level = os.environ.get("TWO_ISLAND_LOG_LEVEL", "").strip()
    if log_level:
        a_peered_data["node"]["log_level"] = log_level
        b_peered_data["node"]["log_level"] = log_level

    a_peered = resign_if_needed(a_peered_data, a_dir / "secrets")
    b_peered = resign_if_needed(b_peered_data, b_dir / "secrets")

    a_peered_path = a_dir / "island-init" / "data" / "two-island-peered.yaml"
    b_peered_path = b_dir / "island-init" / "data" / "two-island-peered.yaml"
    a_peered_path.parent.mkdir(parents=True, exist_ok=True)
    b_peered_path.parent.mkdir(parents=True, exist_ok=True)
    dump(a_peered, a_peered_path)
    dump(b_peered, b_peered_path)

    run(["island-init", "render", "--file", str(a_peered_path), "--repo-root", str(a_dir)])
    run(["island-init", "render", "--file", str(b_peered_path), "--repo-root", str(b_dir)])

    print(f"A ({a_data['island']['id']}) peered with B ({b_data['island']['id']}); both rendered.")


if __name__ == "__main__":
    main()
