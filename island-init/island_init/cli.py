"""island-init: validate, render, bootstrap, and (later) serve, island.yaml (WBS 2.1)."""
from __future__ import annotations

import json
import re
from pathlib import Path

import click

from . import __version__, wizard
from .apply import ApplyError, apply_draft
from .checks import check_wireguard_key_matches, run_semantic_checks
from .crypto import generate_signing_keypair, generate_wireguard_keypair
from .issues import Issue
from .migrate import MigrateError, migrate_document, resign
from .render import RenderError, format_diff, render_all, write_all
from .schema import validate_schema
from .yaml_io import dump, load

EXAMPLE_RELATIVE_TO_REPO_ROOT = "island-init/island.example.yaml"
NEW_ISLAND_DEFAULT_RELATIVE_TO_REPO_ROOT = "island-init/island.yaml"
DEFAULT_SECRETS_DIR_RELATIVE_TO_REPO_ROOT = "secrets"

ID_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
COUNTRY_RE = re.compile(r"^[A-Z]{2}$")
VALID_NODE_CLASSES = ("a", "b", "c", "dev")


@click.group()
@click.version_option(version=__version__, prog_name="island-init")
def main() -> None:
    """island-init -- island.yaml validation and tooling (WBS 2.1)."""


def _issues_for(data, secrets_dir: Path | None = None) -> list[Issue]:
    issues = validate_schema(data)
    if not issues:
        issues = run_semantic_checks(data, data)
        # 3.3-b follow-up 4: a separate call, not folded into
        # run_semantic_checks -- this is the one check that needs
        # filesystem access beyond the document itself (see its own
        # docstring). Runs even if run_semantic_checks found nothing, so
        # a document that's otherwise perfectly valid still catches key
        # drift.
        issues = issues + check_wireguard_key_matches(data, data, secrets_dir)
    return issues


def _validated(file: Path, secrets_dir: Path | None = None):
    """Loads FILE and runs schema + semantic checks; prints issues (if any)
    to stderr and returns None so callers can bail without re-validating."""
    data = load(file)
    issues = _issues_for(data, secrets_dir)
    if issues:
        for issue in issues:
            click.echo(issue.render(str(file)), err=True)
        return None
    return data


@main.command("check")
@click.argument("file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--repo-root",
    "repo_root_option",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=Path("."),
    show_default=True,
    help="Root of the ResCCOM checkout, for locating secrets/ (the WireGuard key-drift check, 3.3-b follow-up 4).",
)
def check(file: Path, repo_root_option: Path) -> None:
    """Validate FILE against the island.yaml schema and semantic rules.

    Schema errors (missing/malformed fields) are reported first; semantic
    checks (PCI uniqueness, non-overlapping prefixes, production-profile
    rules) only run once the document at least parses as YAML, since they
    assume the shape schema validation would otherwise have rejected. If
    a declared `overlay.wireguard_public_key` doesn't match the private
    key at `<repo-root>/secrets/<island id>/wireguard.key` (when that file
    exists), that fails too.
    """
    secrets_dir = repo_root_option.resolve() / DEFAULT_SECRETS_DIR_RELATIVE_TO_REPO_ROOT
    if _validated(file, secrets_dir) is None:
        raise click.exceptions.Exit(1)
    click.echo(f"{file}: OK")


@main.command("render")
@click.option(
    "--lab",
    "use_lab",
    is_flag=True,
    help=f"Render {EXAMPLE_RELATIVE_TO_REPO_ROOT} (the committed lab profile).",
)
@click.option(
    "--file",
    "file_option",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="island.yaml to render (required unless --lab).",
)
@click.option(
    "--diff",
    "show_diff",
    is_flag=True,
    help="Show what would change without writing any file.",
)
@click.option(
    "--repo-root",
    "repo_root_option",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=Path("."),
    show_default=True,
    help="Root of the ResCCOM checkout (the directory containing stack/).",
)
def render(use_lab: bool, file_option: Path | None, show_diff: bool, repo_root_option: Path) -> None:
    """Render island.yaml into stack/core, stack/services, stack/backhaul configs.

    Idempotent: rendering the already-committed lab profile reproduces
    those files byte-for-byte (TASKS.md's "golden rule"). Only fails
    schema/semantic checks or --file are checked; --lab and --file are
    mutually exclusive.
    """
    if use_lab == bool(file_option):
        raise click.UsageError("give exactly one of --lab or --file")

    repo_root = repo_root_option.resolve()
    file = (repo_root / EXAMPLE_RELATIVE_TO_REPO_ROOT) if use_lab else file_option
    if not file.exists():
        raise click.UsageError(f"{file} does not exist")

    secrets_dir = repo_root / DEFAULT_SECRETS_DIR_RELATIVE_TO_REPO_ROOT
    data = _validated(file, secrets_dir)
    if data is None:
        raise click.exceptions.Exit(1)

    try:
        files = render_all(data, repo_root)
    except RenderError as exc:
        raise click.ClickException(str(exc)) from exc

    if show_diff:
        click.echo(format_diff(files), nl=False)
        return

    written = write_all(files, repo_root)
    for f in files:
        status = "written" if f in written else "unchanged"
        click.echo(f"{f.path}: {status}")


def _prompt_matching(prompt: str, pattern: re.Pattern, hint: str) -> str:
    while True:
        value = click.prompt(prompt)
        if pattern.match(value):
            return value
        click.echo(f"  invalid: {hint}", err=True)


def _prompt_node_classes() -> list[str]:
    while True:
        raw = click.prompt(f"Node class(es), comma-separated ({'/'.join(VALID_NODE_CLASSES)})")
        classes = [c.strip() for c in raw.split(",") if c.strip()]
        if classes and all(c in VALID_NODE_CLASSES for c in classes):
            return classes
        click.echo(f"  invalid: each class must be one of {VALID_NODE_CLASSES}", err=True)


@main.command("new")
@click.option("--lab", "use_lab", is_flag=True, help="Build the lab profile non-interactively (reproduces island.example.yaml, minus keys).")
@click.option(
    "--allocation",
    "allocation_option",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Registry allocation file (RFC-0005 D2) to paste in -- required unless --lab or --file.",
)
@click.option(
    "--file",
    "file_option",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Build from an arbitrary island.yaml-shaped file (3.3-b follow-up 1) -- --lab generalized to any such source, e.g. a second lab island fixture. Required unless --lab or --allocation.",
)
@click.option(
    "--out",
    "out_option",
    type=click.Path(dir_okay=False, path_type=Path),
    help=f"Where to write the signed island.yaml (default: {NEW_ISLAND_DEFAULT_RELATIVE_TO_REPO_ROOT}).",
)
@click.option(
    "--secrets-dir",
    "secrets_dir_option",
    type=click.Path(file_okay=False, path_type=Path),
    help=f"Where to write private keys (default: {DEFAULT_SECRETS_DIR_RELATIVE_TO_REPO_ROOT}/, gitignored).",
)
@click.option(
    "--repo-root",
    "repo_root_option",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=Path("."),
    show_default=True,
    help="Root of the ResCCOM checkout (the directory containing stack/).",
)
def new(
    use_lab: bool,
    allocation_option: Path | None,
    file_option: Path | None,
    out_option: Path | None,
    secrets_dir_option: Path | None,
    repo_root_option: Path,
) -> None:
    """Build and sign a fresh island.yaml (RFC-0005 D4's wizard).

    Generates a per-deployment signing keypair and WireGuard keypair,
    writes the private halves to a gitignored secrets/ path, and signs the
    resulting island.yaml -- `check` verifies that signature. --lab,
    --file, and --allocation are mutually exclusive; --lab and --file
    skip every prompt.
    """
    if sum(bool(x) for x in (use_lab, allocation_option, file_option)) != 1:
        raise click.UsageError("give exactly one of --lab, --file, or --allocation")

    repo_root = repo_root_option.resolve()
    out_path = (out_option or (repo_root / NEW_ISLAND_DEFAULT_RELATIVE_TO_REPO_ROOT)).resolve()
    secrets_dir = (secrets_dir_option or (repo_root / DEFAULT_SECRETS_DIR_RELATIVE_TO_REPO_ROOT)).resolve()

    try:
        if use_lab:
            data = wizard.load_lab_identity(repo_root)
        elif file_option:
            data = wizard.load_identity_from_file(file_option)
        else:
            allocations = wizard.load_allocation(allocation_option)
            island_id = _prompt_matching("Island id (short slug)", ID_RE, "lowercase letters/digits/hyphens, e.g. 'example-atoll'")
            display_name = click.prompt("Display name")
            country = _prompt_matching(
                "Country (ISO 3166-1 alpha-2, e.g. FR; XA-XZ for non-production)",
                COUNTRY_RE,
                "two uppercase letters",
            )
            node_classes = _prompt_node_classes()
            profile = click.prompt("Profile", type=click.Choice(["lab", "production"]), default="production")
            if profile == "production":
                assoc = click.prompt("Portal association name (shown on portal.island)")
                contact = click.prompt("Operator contact (shown on portal.island)")
            else:
                assoc = click.prompt("Portal association name (optional, Enter to skip)", default="", show_default=False) or None
                contact = click.prompt("Operator contact (optional, Enter to skip)", default="", show_default=False) or None
            data = wizard.build_island(
                island_id=island_id,
                display_name=display_name,
                country=country,
                node_classes=node_classes,
                profile=profile,
                allocations=allocations,
                portal_association_name=assoc,
                portal_operator_contact=contact,
            )
    except wizard.WizardError as exc:
        raise click.ClickException(str(exc)) from exc

    signing = generate_signing_keypair()
    wg_private_b64, wg_public_b64 = generate_wireguard_keypair()
    wizard.apply_keys(data, signing, wg_public_b64)

    issues = _issues_for(data)
    if issues:
        for issue in issues:
            click.echo(issue.render(str(out_path)), err=True)
        raise click.exceptions.Exit(1)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    dump(data, out_path)
    signing_path, wg_path = wizard.write_secrets(secrets_dir, data["island"]["id"], signing, wg_private_b64)

    click.echo(f"wrote {out_path}")
    click.echo(f"wrote {signing_path} (signing private key -- keep offline, never commit)")
    click.echo(f"wrote {wg_path} (WireGuard private key -- keep offline, never commit)")


@main.command("apply")
@click.option(
    "--draft",
    "draft_option",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Draft island.yaml candidate staged by the Island Console (or hand-edited).",
)
@click.option(
    "--island-yaml",
    "island_yaml_option",
    type=click.Path(dir_okay=False, path_type=Path),
    help=f"island.yaml to sign and update (default: {NEW_ISLAND_DEFAULT_RELATIVE_TO_REPO_ROOT}).",
)
@click.option(
    "--secrets-dir",
    "secrets_dir_option",
    type=click.Path(file_okay=False, path_type=Path),
    help=f"Where the signing private key lives (default: {DEFAULT_SECRETS_DIR_RELATIVE_TO_REPO_ROOT}/).",
)
@click.option(
    "--repo-root",
    "repo_root_option",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=Path("."),
    show_default=True,
    help="Root of the ResCCOM checkout (the directory containing stack/).",
)
def apply_(
    draft_option: Path,
    island_yaml_option: Path | None,
    secrets_dir_option: Path | None,
    repo_root_option: Path,
) -> None:
    """Sign and apply a draft the Island Console staged (RFC-0006 D5, 2.1-f).

    The host-side half of "Apply": re-validates the draft, signs it with
    the private key (which never leaves the host or enters the console
    container), renders every affected config, writes island.yaml, and
    restarts the containers whose rendered config actually changed. Run
    by an operator on the node -- normally via `island.sh apply`, which
    points this at the console's staged draft.
    """
    repo_root = repo_root_option.resolve()
    island_yaml_path = (island_yaml_option or (repo_root / NEW_ISLAND_DEFAULT_RELATIVE_TO_REPO_ROOT)).resolve()
    secrets_dir = (secrets_dir_option or (repo_root / DEFAULT_SECRETS_DIR_RELATIVE_TO_REPO_ROOT)).resolve()

    try:
        result = apply_draft(draft_option.resolve(), island_yaml_path, secrets_dir, repo_root)
    except ApplyError as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo(f"signed and wrote {island_yaml_path}")
    for path in result["changed"]:
        click.echo(f"changed: {path}")
    for container in result["restarted"]:
        click.echo(f"restarted: {container}")
    if not result["changed"]:
        click.echo("no rendered files changed")


@main.command("migrate")
@click.argument("file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--out",
    "out_option",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Where to write the migrated island.yaml (default: FILE itself, in place).",
)
@click.option(
    "--secrets-dir",
    "secrets_dir_option",
    type=click.Path(file_okay=False, path_type=Path),
    help=f"Where the signing private key lives, if FILE is signed (default: {DEFAULT_SECRETS_DIR_RELATIVE_TO_REPO_ROOT}/).",
)
@click.option(
    "--repo-root",
    "repo_root_option",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=Path("."),
    show_default=True,
    help="Root of the ResCCOM checkout (the directory containing stack/).",
)
def migrate(
    file: Path,
    out_option: Path | None,
    secrets_dir_option: Path | None,
    repo_root_option: Path,
) -> None:
    """Bring FILE current with schema fields added since it was generated
    (3.3-b follow-up 5): fills in defaults for anything new (`node`,
    `federation.peers`, `island.overlay.address`) and re-signs FILE with
    the private key in --secrets-dir if it was already signed. A document
    already current is left untouched and reported as such.
    """
    repo_root = repo_root_option.resolve()
    secrets_dir = (secrets_dir_option or (repo_root / DEFAULT_SECRETS_DIR_RELATIVE_TO_REPO_ROOT)).resolve()
    out_path = (out_option or file).resolve()

    data = json.loads(json.dumps(load(file)))  # strip ruamel wrappers, same as wizard._plain
    was_signed = bool(data.get("signature"))
    migrated, changed = migrate_document(data)

    if not changed:
        click.echo(f"{file}: already current, nothing to migrate")
        return

    if was_signed:
        try:
            resign(migrated, secrets_dir)
        except MigrateError as exc:
            raise click.ClickException(str(exc)) from exc

    issues = _issues_for(migrated, secrets_dir)
    if issues:
        for issue in issues:
            click.echo(issue.render(str(out_path)), err=True)
        raise click.exceptions.Exit(1)

    dump(migrated, out_path)
    for field in changed:
        click.echo(f"filled in: {field}")
    click.echo(f"wrote {out_path}" + (" (re-signed)" if was_signed else ""))


if __name__ == "__main__":
    main()
