#!/usr/bin/env python3
"""ResCCOM 2.1-d/2.1-f — Island Console: console.island.

An editor over island.yaml (RFC-0006 D1) — never a second config store.
Reuses island_init directly (the same schema, semantic checks, and
render templates `island-init check`/`render` use) so "render --diff
from the console equals the CLI's output" holds by construction: both
call island_init.render.format_diff on the output of
island_init.render.render_all, not two hand-maintained implementations.

2.1-f trust boundary (SECURITY.md's lab-profile register has the current
row): this container never holds the association's private signing key,
never gets the host's Docker socket, and never gets a read-write mount
of the repo. It only edits and validates a *draft* -- an unsigned
candidate written to /data/console-state/draft.yaml once it passes
schema + semantic checks. Signing island.yaml, rendering, writing, and
restarting affected services all happen host-side (island_init.apply,
run via `island.sh apply`) — see that module's own header comment for
why. Every write endpoint here (every POST) requires the per-boot
operator token island.sh writes to data/console/operator-token; GET
endpoints (map/status/current island.yaml) need none.
"""
from __future__ import annotations

import hmac
import json
import re
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, "/app")

from island_init.apply import build_candidate  # noqa: E402
from island_init.checks import run_semantic_checks  # noqa: E402
from island_init.render import RenderError, format_diff, render_all  # noqa: E402
from island_init.schema import validate_schema  # noqa: E402
from island_init.yaml_io import dump, load  # noqa: E402

import coverage  # noqa: E402

ISLAND_YAML = Path("/data/island.yaml")
REPO_ROOT = Path("/repo")
CONSOLE_STATE = Path("/data/console-state")
DRAFT_PATH = CONSOLE_STATE / "draft.yaml"
DRAFT_META_PATH = CONSOLE_STATE / "draft-meta.json"
OPERATOR_TOKEN_PATH = CONSOLE_STATE / "operator-token"
MEASURED_DIR = CONSOLE_STATE / "measured"
DRAFT_LOG = CONSOLE_STATE / "console-draft.log"
STATIC_DIR = Path("/app/static")
VENDOR_DIR = Path("/app/vendor")


class ApplyError(Exception):
    pass


# CSV filenames are built from site_id (path.rpartition on a URL
# segment) -- reject anything but a plain identifier before it ever
# touches a filesystem path, regardless of what the schema itself
# constrains island.yaml's own site.id to.
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _validated_site_id(site_id: str) -> str:
    if not SAFE_ID_RE.match(site_id):
        raise ApplyError(f"invalid site id {site_id!r}")
    return site_id


def _plain(data) -> dict:
    """Strips ruamel's CommentedMap/CommentedSeq wrappers via a JSON
    round-trip -- what's left is exactly what a candidate document needs
    to be to validate/render/dump cleanly (same reasoning as
    island_init.apply._plain / wizard._plain)."""
    return json.loads(json.dumps(data))


def load_current() -> dict:
    if not ISLAND_YAML.exists():
        raise ApplyError(f"{ISLAND_YAML} does not exist -- run island-init new first")
    return _plain(load(ISLAND_YAML))


def validate(candidate: dict) -> list:
    issues = validate_schema(candidate)
    if not issues:
        issues = run_semantic_checks(candidate, candidate)
    return issues


def load_draft_meta() -> dict | None:
    if not DRAFT_PATH.exists() or not DRAFT_META_PATH.exists():
        return None
    try:
        return json.loads(DRAFT_META_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def log_draft(staged_at: str, changed_paths: list[str]) -> None:
    """Best-effort audit trail for staging a draft -- the actual apply
    (sign/render/restart) is logged separately, host-side, by
    island_init.apply.log_apply."""
    try:
        DRAFT_LOG.parent.mkdir(parents=True, exist_ok=True)
        entry = {"staged_at": staged_at, "changed_files": changed_paths}
        with DRAFT_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError as exc:
        sys.stderr.write(f"log_draft: failed to write {DRAFT_LOG}: {exc}\n")


def do_preview(posted: dict) -> dict:
    current = load_current()
    candidate = build_candidate(current, posted)
    issues = validate(candidate)
    if issues:
        return {"ok": False, "issues": [asdict(i) for i in issues]}
    try:
        files = render_all(candidate, REPO_ROOT)
    except RenderError as exc:
        return {"ok": False, "issues": [{"field": "render", "message": str(exc), "line": None}]}
    return {"ok": True, "issues": [], "diff": format_diff(files)}


def do_save_draft(posted: dict) -> dict:
    """Validates the posted candidate and, if clean, stages it as the
    pending draft -- this never touches island.yaml, never signs
    anything, and never restarts a service; that's `island.sh apply`'s
    job, run by an operator on the host (RFC-0006 D5)."""
    current = load_current()
    candidate = build_candidate(current, posted)
    issues = validate(candidate)
    if issues:
        return {"ok": False, "issues": [asdict(i) for i in issues]}

    try:
        files = render_all(candidate, REPO_ROOT)
    except RenderError as exc:
        return {"ok": False, "issues": [{"field": "render", "message": str(exc), "line": None}]}

    CONSOLE_STATE.mkdir(parents=True, exist_ok=True)
    dump(candidate, DRAFT_PATH)
    staged_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    changed_paths = [f.path for f in files if f.changed]
    DRAFT_META_PATH.write_text(json.dumps({"staged_at": staged_at}), encoding="utf-8")
    log_draft(staged_at, changed_paths)

    return {"ok": True, "issues": [], "diff": format_diff(files), "pending": True, "staged_at": staged_at}


def do_draft_status() -> dict:
    meta = load_draft_meta()
    if meta is None:
        return {"pending": False, "staged_at": None}
    return {"pending": True, "staged_at": meta.get("staged_at")}


def do_predicted_coverage(current: dict) -> dict:
    features = []
    for site in current.get("sites") or []:
        for i, cell in enumerate(site.get("cells") or []):
            feature = coverage.predicted_coverage_feature(site, i, cell)
            if feature is not None:
                features.append(feature)
    return {"type": "FeatureCollection", "features": features, "model": coverage.MODEL_NAME}


def save_measured_csv(site_id: str, cell_index: int, csv_bytes: bytes) -> dict:
    """Stores the CSV and stages a draft pointing the cell's
    measured_points.file_ref at it -- goes through the exact same
    validate-then-stage path as any other edit (do_save_draft), never a
    shortcut straight to island.yaml."""
    site_id = _validated_site_id(site_id)
    MEASURED_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{site_id}-{cell_index}.csv"
    (MEASURED_DIR / filename).write_bytes(csv_bytes)

    current = load_current()
    candidate = json.loads(json.dumps(current))
    for site in candidate.get("sites") or []:
        if site["id"] != site_id:
            continue
        cells = site.get("cells") or []
        if cell_index >= len(cells):
            raise ApplyError(f"site {site_id!r} has no cell index {cell_index}")
        cells[cell_index]["measured_points"] = {"file_ref": f"measured/{filename}"}
    return do_save_draft(candidate)


def load_measured_points(site_id: str, cell_index: int) -> dict:
    site_id = _validated_site_id(site_id)
    path = MEASURED_DIR / f"{site_id}-{cell_index}.csv"
    if not path.exists():
        return {"type": "FeatureCollection", "features": []}
    features = []
    import csv as csv_module

    with path.open(newline="", encoding="utf-8") as f:
        for row in csv_module.DictReader(f):
            try:
                lat = float(row["lat"])
                lon = float(row["lon"])
            except (KeyError, ValueError):
                continue
            features.append(
                {
                    "type": "Feature",
                    "properties": {
                        "rsrp": row.get("rsrp"),
                        "rsrq": row.get("rsrq"),
                        "timestamp": row.get("timestamp"),
                    },
                    "geometry": {"type": "Point", "coordinates": [lon, lat]},
                }
            )
    return {"type": "FeatureCollection", "features": features}


MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json",
}


def _operator_token_valid(provided: str) -> bool:
    if not OPERATOR_TOKEN_PATH.exists():
        return False
    expected = OPERATOR_TOKEN_PATH.read_text(encoding="utf-8").strip()
    return bool(expected) and hmac.compare_digest(provided, expected)


class Handler(BaseHTTPRequestHandler):
    server_version = "island-console/2.1-f"

    def _send_json(self, status: int, body: dict) -> None:
        payload = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _send_file(self, path: Path) -> None:
        if not path.exists() or not path.is_file():
            self._send_json(404, {"error": "not found"})
            return
        content_type = MIME_TYPES.get(path.suffix, "application/octet-stream")
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def _has_valid_operator_token(self) -> bool:
        auth = self.headers.get("Authorization", "")
        prefix = "Bearer "
        provided = auth[len(prefix) :] if auth.startswith(prefix) else ""
        return _operator_token_valid(provided)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/" or path == "/index.html":
            self._send_file(STATIC_DIR / "index.html")
        elif path == "/style.json":
            self._send_file(STATIC_DIR / "style.json")
        elif path.startswith("/app.js") or path.startswith("/style.css"):
            self._send_file(STATIC_DIR / path.lstrip("/"))
        elif path.startswith("/vendor/"):
            self._send_file(VENDOR_DIR / path[len("/vendor/") :])
        elif path == "/api/island":
            try:
                self._send_json(200, load_current())
            except ApplyError as exc:
                self._send_json(503, {"error": str(exc)})
        elif path == "/api/draft":
            self._send_json(200, do_draft_status())
        elif path == "/api/coverage/predicted":
            try:
                self._send_json(200, do_predicted_coverage(load_current()))
            except ApplyError as exc:
                self._send_json(503, {"error": str(exc)})
        elif path.startswith("/api/coverage/measured/"):
            rest = path[len("/api/coverage/measured/") :]
            site_id, _, cell_index = rest.rpartition("-")
            try:
                self._send_json(200, load_measured_points(site_id, int(cell_index)))
            except ValueError:
                self._send_json(400, {"error": "expected /api/coverage/measured/<site_id>-<cell_index>"})
            except ApplyError as exc:
                self._send_json(400, {"error": str(exc)})
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):
        # Every write endpoint needs the per-boot operator token; read-only
        # map/status is all served from do_GET, which needs none (2.1-f).
        if not self._has_valid_operator_token():
            self._send_json(401, {"error": "missing or invalid operator token"})
            return

        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/preview":
            try:
                self._send_json(200, do_preview(self._read_json_body()))
            except ApplyError as exc:
                self._send_json(503, {"error": str(exc)})
        elif path == "/api/draft":
            try:
                self._send_json(200, do_save_draft(self._read_json_body()))
            except ApplyError as exc:
                self._send_json(503, {"error": str(exc)})
        elif path.startswith("/api/measured/"):
            rest = path[len("/api/measured/") :]
            site_id, _, cell_index = rest.rpartition("-")
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length)
            try:
                self._send_json(200, save_measured_csv(site_id, int(cell_index), body))
            except (ApplyError, ValueError) as exc:
                self._send_json(400, {"error": str(exc)})
        else:
            self._send_json(404, {"error": "not found"})

    def log_message(self, fmt, *args):
        pass


if __name__ == "__main__":
    server = ThreadingHTTPServer(("0.0.0.0", 80), Handler)
    server.serve_forever()
