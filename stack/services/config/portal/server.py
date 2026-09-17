#!/usr/bin/env python3
"""ResCCOM 1.3-e — portal.island: the landing page + live status endpoint.

Stdlib only (no pip install, no build step) — this is our own glue, run
directly against the stock python:3.12-alpine image (see
../../compose.yaml), the same "mount a script into an unmodified upstream
image" pattern every other component in this directory uses.

2.1-b: association_name/operator_contact are read from settings.json
(rendered from island.yaml's services.portal_association_name/
portal_operator_contact by island-init render) on every request — cheap,
and correct for a bind-mounted file that can change under a running
container. Null/missing (today's lab profile: island-init new, 2.1-c,
doesn't exist yet, so no island ever has a signed association identity)
falls back to the exact placeholder text this file always showed before
settings.json existed, so the lab profile's rendered page is unchanged.

Every request — any path, any Host header — gets the same rendered
portal page: this is also what CoreDNS's WAN-down fallback
(../coredns/Corefile's `.:5353` block) sends every other domain to when
the island's uplink is down, so a browser mid-page-load elsewhere lands
here exactly like a commercial captive portal.

Status is server-rendered directly into the HTML on every GET / — not
fetched by client-side JS after the fact — so `curl http://portal.island`
alone (1.3-e's own acceptance test) sees live status with no JavaScript
required, and the page still works correctly with JS disabled entirely
(CLAUDE.md/1.3-e: must render on a five-year-old Android browser). A
small XMLHttpRequest-based poll of GET /status (plain JSON, same data)
GET /status exists mainly for that reuse and for scripted checks
(verify.sh); the page itself just reloads on a 15s timer for anyone
leaving it open — an enhancement, not a dependency, and simple enough
that a five-year-old WebView won't choke on it either way. The fallback
for "no JS at all" is simply the page as server-rendered at load time.
"""
import html
import json
import socket
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SETTINGS_PATH = Path(__file__).parent / "settings.json"

# Same services_net addresses as ../../compose.yaml / ../../jitsi/compose.yaml.
# Direct IPs, not .island names: resolving those depends on DNS, which is
# itself one of the things being checked here — a dependency loop worth
# avoiding, not an oversight.
SERVICES = [
    ("Local knowledge library (library.island)", "10.46.0.11", 80, "/"),
    ("Messaging (chat.island)", "10.46.0.20", 80, "/_matrix/client/versions"),
    ("Voice/video calling (talk.island)", "10.46.0.30", 80, "/"),
]
DNS_HOST, DNS_PORT = "10.46.0.53", 53
WAN_PROBE_HOST, WAN_PROBE_PORT = "1.1.1.1", 443
TIMEOUT = 2.0


def check_tcp(host, port, timeout=TIMEOUT):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def check_http(host, port, path, timeout=TIMEOUT):
    try:
        conn_kwargs = {"timeout": timeout}
        url = f"http://{host}:{port}{path}"
        req = urllib.request.Request(url, headers={"Host": "portal.island"})
        with urllib.request.urlopen(req, **conn_kwargs) as resp:
            return 200 <= resp.status < 500
    except Exception:
        return False


def compute_status():
    wan_up = check_tcp(WAN_PROBE_HOST, WAN_PROBE_PORT)
    dns_up = check_tcp(DNS_HOST, DNS_PORT)
    services = []
    for name, host, port, path in SERVICES:
        services.append({"name": name, "up": check_http(host, port, path)})
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "wan_up": wan_up,
        "dns_up": dns_up,
        "services": services,
    }


def load_settings():
    try:
        with SETTINGS_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return {
            "association_name": data.get("association_name") or None,
            "operator_contact": data.get("operator_contact") or None,
        }
    except (OSError, ValueError):
        return {"association_name": None, "operator_contact": None}


PLACEHOLDER_ASSOCIATION_SPAN = '<span class="placeholder">[local association name]</span>'
PLACEHOLDER_CONTACT_PARAGRAPH = (
    '<p class="placeholder">[Where to find the operators in person, a local\n'
    "radio channel or meeting point, and when the network is staffed &mdash;\n"
    "filled in by the operating association for this specific island.]</p>"
)


def association_span(association_name):
    if not association_name:
        return PLACEHOLDER_ASSOCIATION_SPAN
    return html.escape(association_name)


def contact_paragraph(operator_contact):
    if not operator_contact:
        return PLACEHOLDER_CONTACT_PARAGRAPH
    return f"<p>{html.escape(operator_contact)}</p>"


def render_indicator(up):
    return ('<span class="ok">&#10003; up</span>' if up
            else '<span class="down">&#10007; down</span>')


PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Island network &mdash; status</title>
<style>
  body {{ font-family: Georgia, "Times New Roman", serif; background: #fdfaf3; color: #1a1a1a;
         margin: 0; padding: 16px; line-height: 1.5; }}
  .wrap {{ max-width: 640px; margin: 0 auto; }}
  h1 {{ font-size: 1.5em; margin: 0 0 4px 0; }}
  h2 {{ font-size: 1.1em; margin: 1.5em 0 0.4em 0; border-bottom: 1px solid #ccc; padding-bottom: 2px; }}
  p {{ margin: 0.5em 0; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 0.5em; }}
  td {{ padding: 6px 4px; border-bottom: 1px solid #ddd; }}
  td.name {{ }}
  td.state {{ text-align: right; white-space: nowrap; }}
  .ok {{ color: #1a7a1a; font-weight: bold; }}
  .down {{ color: #a01818; font-weight: bold; }}
  .banner {{ padding: 10px 12px; margin: 10px 0; border: 1px solid; }}
  .banner.up {{ background: #eaf6ea; border-color: #1a7a1a; }}
  .banner.down {{ background: #f8ecec; border-color: #a01818; }}
  .meta {{ color: #666; font-size: 0.85em; margin-top: 1.5em; }}
  .placeholder {{ background: #fff6e0; border: 1px dashed #b8952f; padding: 8px 10px; }}
</style>
</head>
<body>
<div class="wrap">

<h1>This is a private island network</h1>
<p>You are connected to a small, local 4G/5G network run by
{association_span} for this
community. It is not connected to any national mobile carrier. When the
internet link below is down, everything on this page still works.</p>

<div class="banner {wan_class}">
  <strong>Internet (WAN) uplink: {wan_state}</strong><br>
  {wan_detail}
</div>

<h2>What works right now</h2>
<table>
{service_rows}
<tr><td class="name">Local DNS</td><td class="state">{dns_indicator}</td></tr>
</table>

<h2>What is and isn't protected here</h2>
<p><strong>Protected:</strong> chat messages sent through this network's
messaging service are end-to-end encrypted by default &mdash; nobody
operating this network, including the local operators, can read them.
Your phone's connection to this tower uses the same standard mobile
encryption and authentication as any commercial 4G/5G network.</p>
<p><strong>Not protected, and not claimed to be:</strong> this network is
not anonymous, hidden, or covert. Like any cell tower, a capable observer
can detect that it exists and who is connected to it. This is a
resilience tool for a local community during a disruption &mdash; it is
not designed to protect anyone from a state-level adversary, and you
should not rely on it for that.</p>

<h2>Reaching the local operators</h2>
{contact_paragraph}

<p class="meta">Status generated {generated_at}. This page refreshes
itself every 15 seconds while open; the same status is always current if
JavaScript is off &mdash; reload the page.</p>
</div>
<script>
setTimeout(function() {{ location.reload(); }}, 15000);
</script>
</body>
</html>
"""


def render_page(status):
    wan_up = status["wan_up"]
    rows = "\n".join(
        '<tr><td class="name">{}</td><td class="state">{}</td></tr>'.format(
            s["name"], render_indicator(s["up"])
        )
        for s in status["services"]
    )
    settings = load_settings()
    return PAGE_TEMPLATE.format(
        wan_class="up" if wan_up else "down",
        wan_state="up" if wan_up else "down",
        wan_detail=(
            "This island can also reach the wider internet right now."
            if wan_up else
            "This island is currently running on local power alone &mdash; "
            "everything above still works."
        ),
        service_rows=rows,
        dns_indicator=render_indicator(status["dns_up"]),
        generated_at=status["generated_at"],
        association_span=association_span(settings["association_name"]),
        contact_paragraph=contact_paragraph(settings["operator_contact"]),
    )


class Handler(BaseHTTPRequestHandler):
    server_version = "portal-island/1.3-e"

    def _send(self, body_bytes, content_type):
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body_bytes)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body_bytes)

    def do_GET(self):
        status = compute_status()
        if self.path.rstrip("/") == "/status":
            self._send(json.dumps(status).encode("utf-8"), "application/json")
        else:
            self._send(render_page(status).encode("utf-8"), "text/html; charset=utf-8")

    def log_message(self, fmt, *args):
        pass


if __name__ == "__main__":
    server = ThreadingHTTPServer(("0.0.0.0", 80), Handler)
    server.serve_forever()
