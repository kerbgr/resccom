"""resccom-sim: CLI for association-run subscriber & SIM provisioning.

The full command surface from sim-tools/TASKS.md exists here. `sub
add|list|remove` (3.2-a) and `db sync` (3.2-b) are implemented. `sub
export` and `sim program|verify` need the label-printer/pySim
integrations from 3.2-c/d and are left as clearly-labelled stubs — do not
fill them in ahead of those tasks.
"""
from __future__ import annotations

import os
from pathlib import Path

import click

from . import __version__
from .crypto import DecryptionError
from .model import TEST_KEY, TEST_OPC, Subscriber, SubscriberError, generate_test_imsi
from .roaming import (
    RoamingExportError,
    RoamingImportError,
    export_policy_records,
    read_import_file,
    run_import,
    run_list,
    run_remove,
    write_export_file,
)
from .store import SubscriberConflictError, SubscriberExistsError, SubscriberStore
from .sync import SyncError, run_sync

STORE_ENV = "RESCCOM_SIM_STORE"
PASSPHRASE_ENV = "RESCCOM_SIM_PASSPHRASE"
DEFAULT_STORE = Path(click.get_app_dir("resccom-sim")) / "subscribers.db.enc"

NOT_YET_IMPLEMENTED = (
    "{command} is not implemented yet (WBS {wbs}) "
    "-- this is a CLI skeleton for 3.2-a."
)


def _store_path(store_option: str | None) -> Path:
    if store_option:
        return Path(store_option).expanduser()
    if os.environ.get(STORE_ENV):
        return Path(os.environ[STORE_ENV]).expanduser()
    return DEFAULT_STORE


def _passphrase(*, new_store: bool) -> str:
    env = os.environ.get(PASSPHRASE_ENV)
    if env is not None:
        return env
    prompt = "New store passphrase" if new_store else "Store passphrase"
    return click.prompt(prompt, hide_input=True, confirmation_prompt=new_store)


def _open_store(ctx: click.Context) -> SubscriberStore:
    path: Path = ctx.obj["store_path"]
    store = SubscriberStore(path, _passphrase(new_store=not path.exists()))
    try:
        store.imsis()  # fail fast on a wrong passphrase before mutating anything
    except DecryptionError as exc:
        raise click.ClickException(str(exc)) from exc
    return store


@click.group()
@click.option(
    "--store",
    "store_option",
    default=None,
    help=f"Path to the encrypted subscriber store (default: {DEFAULT_STORE}, or ${STORE_ENV}).",
)
@click.version_option(version=__version__, prog_name="resccom-sim")
@click.pass_context
def main(ctx: click.Context, store_option: str | None) -> None:
    """resccom-sim -- manage ResCCOM subscribers and SIMs (WBS 3.2)."""
    ctx.ensure_object(dict)
    ctx.obj["store_path"] = _store_path(store_option)


@main.group()
def sub() -> None:
    """Manage subscribers in the local encrypted store."""


@sub.command("add")
@click.option(
    "--test",
    "is_test",
    is_flag=True,
    help="Generate a test-PLMN (001/01) subscriber using the well-known 3GPP test K/OPc.",
)
@click.option("--imsi", default=None, help="15-digit IMSI (required unless --test).")
@click.option("--key", default=None, help="32 hex-char subscriber key K (required unless --test).")
@click.option("--opc", default=None, help="32 hex-char OPc (required unless --test).")
@click.option("--label", default="", help="Human-readable label (name or device tag).")
@click.option("--notes", "node_class_notes", default="", help="Free-text node-class notes.")
@click.option(
    "--home-routed",
    "home_routed",
    is_flag=True,
    help=(
        "Home-Routed roaming: this subscriber's roaming PDU sessions anchor at its home"
        " island's SMF/UPF instead of the visited island's (RFC-0003 D1's default is"
        " Local Breakout -- the visited island serves the session)."
    ),
)
@click.option(
    "--if-missing",
    "if_missing",
    is_flag=True,
    help=(
        "Idempotent: succeed without error if an identical subscriber with this IMSI"
        " already exists; still error on a conflicting one. For rigs sharing one dev"
        " store -- each rig adds its own IMSI this way instead of `rm -f`-ing the store."
    ),
)
@click.pass_context
def sub_add(
    ctx: click.Context,
    is_test: bool,
    imsi: str | None,
    key: str | None,
    opc: str | None,
    label: str,
    node_class_notes: str,
    home_routed: bool,
    if_missing: bool,
) -> None:
    """Add a subscriber to the local store."""
    store = _open_store(ctx)

    if is_test:
        imsi = imsi or generate_test_imsi(store.imsis())
        key = key or TEST_KEY
        opc = opc or TEST_OPC
    elif imsi is None or key is None or opc is None:
        raise click.UsageError("--imsi, --key and --opc are required unless --test is given.")

    try:
        subscriber = Subscriber(
            imsi=imsi, key=key, opc=opc, label=label, node_class_notes=node_class_notes,
            lbo_roaming_allowed=not home_routed,
        )
    except SubscriberError as exc:
        raise click.ClickException(str(exc)) from exc

    if if_missing:
        try:
            added = store.add_if_missing(subscriber)
        except SubscriberConflictError as exc:
            raise click.ClickException(str(exc)) from exc
        click.echo(f"added {subscriber.imsi}" if added else f"already present: {subscriber.imsi}")
        return

    try:
        store.add(subscriber)
    except SubscriberExistsError as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo(f"added {subscriber.imsi}")


@sub.command("list")
@click.option("--show-secrets", is_flag=True, help="Also print K and OPc (hidden by default).")
@click.pass_context
def sub_list(ctx: click.Context, show_secrets: bool) -> None:
    """List subscribers in the local store."""
    store = _open_store(ctx)
    subscribers = store.list_all()
    if not subscribers:
        click.echo("(no subscribers)")
        return
    for s in subscribers:
        roaming = "LBO" if s.lbo_roaming_allowed else "HR"
        line = f"{s.imsi}  {s.label or '-':<20}  {roaming}"
        if show_secrets:
            line += f"  key={s.key} opc={s.opc}"
        click.echo(line)


@sub.command("show")
@click.argument("imsi")
@click.option("--show-secrets", is_flag=True, help="Also print K and OPc (hidden by default).")
@click.pass_context
def sub_show(ctx: click.Context, imsi: str, show_secrets: bool) -> None:
    """Show one subscriber's details, including its roaming policy."""
    store = _open_store(ctx)
    subscriber = next((s for s in store.list_all() if s.imsi == imsi), None)
    if subscriber is None:
        raise click.ClickException(f"no such subscriber: {imsi}")
    roaming = "Local Breakout" if subscriber.lbo_roaming_allowed else "Home-Routed"
    click.echo(f"imsi: {subscriber.imsi}")
    click.echo(f"label: {subscriber.label or '-'}")
    click.echo(f"notes: {subscriber.node_class_notes or '-'}")
    click.echo(f"amf: {subscriber.amf}")
    click.echo(f"roaming: {roaming} (lbo_roaming_allowed={'true' if subscriber.lbo_roaming_allowed else 'false'})")
    click.echo(f"created_at: {subscriber.created_at}")
    if show_secrets:
        click.echo(f"key: {subscriber.key}")
        click.echo(f"opc: {subscriber.opc}")


@sub.command("edit")
@click.argument("imsi")
@click.option(
    "--home-routed",
    "home_routed",
    is_flag=True,
    help=(
        "Switch this subscriber to Home-Routed roaming (anchors roaming PDU sessions at"
        " its home island). Omit the flag to switch it back to Local Breakout, the"
        " RFC-0003 D1 default."
    ),
)
@click.pass_context
def sub_edit(ctx: click.Context, imsi: str, home_routed: bool) -> None:
    """Edit an existing subscriber's roaming policy (`lbo_roaming_allowed`)."""
    store = _open_store(ctx)
    allowed = not home_routed
    if not store.set_lbo_roaming_allowed(imsi, allowed):
        raise click.ClickException(f"no such subscriber: {imsi}")
    click.echo(f"{imsi}: lbo_roaming_allowed={'true' if allowed else 'false'}")


@sub.command("remove")
@click.argument("imsi")
@click.pass_context
def sub_remove(ctx: click.Context, imsi: str) -> None:
    """Remove a subscriber from the local store (local only -- see WBS 3.2-b to also revoke core access)."""
    store = _open_store(ctx)
    if store.remove(imsi):
        click.echo(f"removed {imsi}")
    else:
        raise click.ClickException(f"no such subscriber: {imsi}")


@sub.command("export")
@click.pass_context
def sub_export(ctx: click.Context) -> None:
    """Export subscribers as CSV for the batch label-printer pipeline."""
    raise click.ClickException(NOT_YET_IMPLEMENTED.format(command="sub export", wbs="3.2-d"))


@main.group()
def db() -> None:
    """Sync the local store with the island's Open5GS core."""


@db.command("sync")
@click.option(
    "--core-dir",
    "core_dir_option",
    default=".",
    show_default=True,
    help="Path to the stack/core compose project (needs a running 'mongo' service).",
)
@click.pass_context
def db_sync(ctx: click.Context, core_dir_option: str) -> None:
    """Reconcile Open5GS's subscriber collection with the local store.

    Upserts every subscriber in the local store (skipping any whose Mongo
    document already matches exactly -- see sync.py's module docstring for
    why that matters for a live session), then deletes any Mongo subscriber
    document whose IMSI is not in the local store -- the local store is
    authoritative, so removing a subscriber locally and syncing revokes its
    core access. Requires `docker compose` and a running `mongo` service in
    --core-dir.
    """
    store = _open_store(ctx)
    subscribers = store.list_all()
    core_dir = Path(core_dir_option).expanduser()
    try:
        result = run_sync(subscribers, core_dir)
    except SyncError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(
        f"added={result.added} updated={result.updated} "
        f"unchanged={result.unchanged} removed={result.removed} ({core_dir}/mongo)"
    )


@main.group()
def roaming() -> None:
    """Export/import subscriber POLICY (never credentials) for inbound roaming (WBS 3.3-c v2h).

    A roaming subscriber's key material never leaves their home island
    (RFC-0003 D1) -- only their `lbo_roaming_allowed` policy travels, so a
    visited island's PCF can complete Local Breakout PDU session
    establishment for them (TASKS.md 3.3-c v2g's review, from
    `lib/dbi/session.c`). See sim-tools/README.md "Inbound roaming".
    """


@roaming.command("export")
@click.option("--imsi", "imsis", multiple=True, help="Export only this IMSI (repeatable). Default: every subscriber with lbo_roaming_allowed=true.")
@click.option("--out", "out_option", required=True, help="Path to write the policy-only export file.")
@click.pass_context
def roaming_export(ctx: click.Context, imsis: tuple[str, ...], out_option: str) -> None:
    """Export policy-only records -- no key, no opc, no security anywhere."""
    store = _open_store(ctx)
    subscribers = store.list_all()
    try:
        records = export_policy_records(subscribers, imsis=list(imsis) or None)
    except RoamingExportError as exc:
        raise click.ClickException(str(exc)) from exc
    out = Path(out_option).expanduser()
    write_export_file(records, out)
    click.echo(f"exported {len(records)} policy-only record(s) to {out}")


@roaming.command("import")
@click.argument("file", type=click.Path(exists=True, dir_okay=False))
@click.option("--core-dir", "core_dir_option", default=".", show_default=True, help="Path to the visited island's stack/core compose project.")
@click.option("--home-plmn", "home_plmn", required=True, help="Home island's PLMN as MCC/MNC, e.g. 001/01.")
def roaming_import(file: str, core_dir_option: str, home_plmn: str) -> None:
    """Import policy-only records as marked inbound-roamer subscribers.

    Refuses any record carrying a credential-like field (security/k/opc/
    amf) and never overwrites an existing unmarked (real local) subscriber
    with the same IMSI.
    """
    if "/" not in home_plmn:
        raise click.UsageError("--home-plmn must be MCC/MNC, e.g. 001/01")
    home_mcc, home_mnc = home_plmn.split("/", 1)
    try:
        records = read_import_file(Path(file).expanduser())
        result = run_import(records, Path(core_dir_option).expanduser(), home_mcc=home_mcc, home_mnc=home_mnc)
    except RoamingImportError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"imported {result.imported} inbound-roamer record(s) (home_plmn={home_mcc}/{home_mnc})")


@roaming.command("list")
@click.option("--core-dir", "core_dir_option", default=".", show_default=True, help="Path to the visited island's stack/core compose project.")
def roaming_list(core_dir_option: str) -> None:
    """List inbound-roamer records currently held at this island."""
    try:
        records = run_list(Path(core_dir_option).expanduser())
    except RoamingImportError as exc:
        raise click.ClickException(str(exc)) from exc
    if not records:
        click.echo("(no inbound-roamer records)")
        return
    for rec in records:
        home_plmn = rec.get("home_plmn", {})
        click.echo(f"{rec['imsi']}  home_plmn={home_plmn.get('mcc', '?')}/{home_plmn.get('mnc', '?')}")


@roaming.command("remove")
@click.argument("imsi")
@click.option("--core-dir", "core_dir_option", default=".", show_default=True, help="Path to the visited island's stack/core compose project.")
def roaming_remove(imsi: str, core_dir_option: str) -> None:
    """Remove one inbound-roamer record by IMSI. Never touches an unmarked subscriber."""
    try:
        removed = run_remove(imsi, Path(core_dir_option).expanduser())
    except RoamingImportError as exc:
        raise click.ClickException(str(exc)) from exc
    if removed:
        click.echo(f"removed {imsi}")
    else:
        raise click.ClickException(f"no inbound-roamer record for {imsi}")


@main.group()
def sim() -> None:
    """Program and verify physical SIM cards. [HW]"""


@sim.command("program")
@click.pass_context
def sim_program(ctx: click.Context) -> None:
    """Write a subscriber's credentials onto a SIM via pySim. [HW]"""
    raise click.ClickException(NOT_YET_IMPLEMENTED.format(command="sim program", wbs="3.2-c"))


@sim.command("verify")
@click.pass_context
def sim_verify(ctx: click.Context) -> None:
    """Read back a programmed SIM and cross-check it against the store. [HW]"""
    raise click.ClickException(NOT_YET_IMPLEMENTED.format(command="sim verify", wbs="3.2-c"))


if __name__ == "__main__":
    main()
