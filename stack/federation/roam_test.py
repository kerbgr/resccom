"""ResCCOM 3.3-c -- roaming test vehicle.

Attempts RFC-0003 D1's home-routed 5G authentication mechanism live, the
way TASKS.md 3.3-c step 1 describes it: register island A's real
AUSF/UDM into island B's NRF with a SUPI range covering A's IMSI block,
then two-island.sh's own `roam` command attaches an A-subscriber via B's
gNB and checks whether B's AMF actually used A's AUSF/UDM for it.

The registration step uses NRF's own Nnrf_NFManagement PUT API directly
(the only mechanism found reachable for "static profile" injection --
see TASKS.md 3.3-c's VERIFY markers) -- this is a test harness exercising
upstream open5gs exactly as shipped (CLAUDE.md "never fork upstreams"),
not a new feature: nothing here is rendered by island-init or runs in a
real island.sh deployment.

Called by ./two-island.sh roam; not meant to run standalone outside that
wrapper's env/PATH/compose setup (needs B_ENV in the process environment
for docker compose to resolve island B's project).
"""
from __future__ import annotations

import ipaddress
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "island-init"))
from island_init.yaml_io import load  # noqa: E402

# Mirrors island_init.render.NODE_IP_OFFSETS's nrf/ausf/udm entries --
# duplicated rather than imported because render.py's own offsets cover
# every NF and this script only ever needs these three (TASKS.md 3.3-c's
# "authentication NFs"); a real island-init render target would import
# it directly, but this is a one-off test harness, not a render target.
NODE_IP_OFFSETS = {"nrf": 10, "ausf": 11, "udm": 12}


def load_plain(path: Path) -> dict:
    return json.loads(json.dumps(load(path)))


def core_net_of(island_yaml: dict) -> ipaddress.IPv4Network:
    base = ipaddress.ip_network(island_yaml["node"]["internal_base"], strict=False)
    return ipaddress.ip_network(f"{base.network_address}/24")


def nf_ip(core_net: ipaddress.IPv4Network, nf: str) -> str:
    return str(core_net.network_address + NODE_IP_OFFSETS[nf])


def supi_range(imsi_block: str) -> dict:
    """A full SUPI is 15 digits (mcc+mnc+msin); imsi_block is the prefix
    this island issues subscribers under (RFC-0005 D2) -- the widest
    range that prefix could mean."""
    return {"start": imsi_block.ljust(15, "0"), "end": imsi_block.ljust(15, "9")}


def nf_profile(*, nf_type: str, instance_id: str, ip: str, plmn: dict, supi: dict, service_name: str) -> dict:
    info_key = {"AUSF": "ausfInfo", "UDM": "udmInfo"}[nf_type]
    return {
        "nfInstanceId": instance_id,
        "nfType": nf_type,
        "nfStatus": "REGISTERED",
        "plmnList": [plmn],
        "ipv4Addresses": [ip],
        info_key: {"supiRanges": [supi]},
        "nfServices": [{
            "serviceInstanceId": f"{instance_id}-svc",
            "serviceName": service_name,
            "versions": [{"apiVersionInUri": "v1", "apiFullVersion": "1.0.0"}],
            "scheme": "http",
            "nfServiceStatus": "REGISTERED",
            "ipEndPoints": [{"ipv4Address": ip, "port": 7777}],
        }],
    }


def curl_into(compose_cmd: list[str], service: str, method: str, url: str, body: str | None = None) -> str:
    cmd = [*compose_cmd, "exec", "-T", service, "curl", "-s", "--http2-prior-knowledge", "-X", method]
    if body is not None:
        cmd += ["-H", "Content-Type: application/json", "-d", "@-"]
    cmd.append(url)
    result = subprocess.run(cmd, input=body, capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(f"curl into {service} failed ({result.returncode}): {result.stderr}")
    return result.stdout


def main() -> None:
    if len(sys.argv) != 4:
        raise SystemExit(f"usage: {sys.argv[0]} <a_repo_root> <b_repo_root> <b_compose_file>")
    a_dir = Path(sys.argv[1]).resolve()
    b_dir = Path(sys.argv[2]).resolve()
    b_compose_file = sys.argv[3]

    a_data = load_plain(a_dir / "island-init" / "island.yaml")
    b_data = load_plain(b_dir / "island-init" / "island.yaml")
    a_core = core_net_of(a_data)
    b_core = core_net_of(b_data)
    plmn = a_data["allocations"]["plmn"]
    supi = supi_range(a_data["allocations"]["imsi_block"])
    b_nrf_ip = nf_ip(b_core, "nrf")
    b_compose_cmd = ["docker", "compose", "-f", b_compose_file]

    a_ausf_ip = nf_ip(a_core, "ausf")
    a_udm_ip = nf_ip(a_core, "udm")
    # Parseable lines two-island.sh's cmd_roam greps out of this script's
    # own stdout, rather than re-deriving node.internal_base's offsets a
    # second time in bash.
    print(f"a_ausf_ip={a_ausf_ip}")
    print(f"a_udm_ip={a_udm_ip}")

    print(f"== registering A's AUSF/UDM into B's NRF ({b_nrf_ip}:7777) with supiRanges {supi} ==")
    for nf_type, service_name, instance_id in (
        ("AUSF", "nausf-auth", "a0000000-0000-0000-0000-00000000ausf"),
        ("UDM", "nudm-ueau", "a0000000-0000-0000-0000-00000000udm0"),
    ):
        ip = nf_ip(a_core, nf_type.lower())
        profile = nf_profile(nf_type=nf_type, instance_id=instance_id, ip=ip, plmn=plmn, supi=supi, service_name=service_name)
        url = f"http://{b_nrf_ip}:7777/nnrf-nfm/v1/nf-instances/{instance_id}"
        curl_into(b_compose_cmd, "nrf", "PUT", url, json.dumps(profile))
        got_raw = curl_into(b_compose_cmd, "nrf", "GET", url)
        try:
            got = json.loads(got_raw)
        except json.JSONDecodeError:
            raise SystemExit(f"B's NRF returned non-JSON for {nf_type} GET: {got_raw!r}")
        info_key = "ausfInfo" if nf_type == "AUSF" else "udmInfo"
        if info_key in got and got[info_key].get("supiRanges"):
            print(f"OK: B's NRF persisted {nf_type} {info_key}.supiRanges: {got[info_key]['supiRanges']}")
        else:
            print(f"NEGATIVE FINDING: B's NRF dropped {info_key}.supiRanges on {nf_type} "
                  f"(instance {instance_id}, ip {ip}) -- persisted profile has no {info_key}: {got_raw}")


if __name__ == "__main__":
    main()
