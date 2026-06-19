#!/usr/bin/env python3

"""KUHBS rofi launcher menu."""

from __future__ import annotations

import html
import shlex
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

# The rofi helper library is copied by this repo, while the KUHBS Python package
# is installed by kuhbs-for-qubes under /usr/share/kuhbs.  Add both paths before
# importing so this script works from i3 without a virtualenv or site-packages install.
sys.path.insert(0, str(Path.home() / ".kuhbs/rofi/lib/python"))
sys.path.insert(0, "/usr/share/kuhbs")

from rofi_common import LABEL_COLORS, RofiRow, die, rofi_dmenu
from kuhbs.config import load_defaults, load_yaml, repo_defaults_path
from kuhbs.launchers import LauncherSpec, launcher_command, launcher_specs
from kuhbs.model import resolve_kuhs

KUHBS_ROOT = Path.home() / ".kuhbs/my-kuhbs"
QUBES_XML = Path("/var/lib/qubes/qubes.xml")
DOM0_TERMINAL_ICON = Path("/usr/share/kuhbs/launcher-icons/xfce4-terminal.svg")
AUTOSTART_TARGET = "all-autostart-launcher-kuhs"


def read_qubes_xml_names() -> set[str]:
    """Read created VM names directly from Qubes' persistent dom0 store."""
    # qubes.xml is nested as domains/domain/properties/property.  The VM name is
    # stored as a property entry instead of an attribute on the domain node, so the
    # code walks the XML tree one level at a time and skips incomplete entries.
    root = ET.parse(QUBES_XML).getroot()
    names: set[str] = set()
    domains = root.find("domains")
    if domains is None:
        die(f"missing domains section in {QUBES_XML}")
    assert domains is not None
    for domain in domains.findall("domain"):
        properties = domain.find("properties")
        if properties is None:
            continue
        # Stop after the first name property for this domain; the remaining
        # properties are unrelated qvm-prefs data.
        for prop in properties.findall("property"):
            if prop.get("name") == "name" and prop.text:
                names.add(prop.text.strip())
                break
    if not names:
        die(f"no VM names found in {QUBES_XML}")
    return names


def dom0_terminal_spec() -> LauncherSpec:
    """Always offer one local dom0 terminal."""
    # Rofi rows all use LauncherSpec, even for dom0.  Keeping dom0 in the same
    # shape means the rendering and selection code does not need a second row type.
    return LauncherSpec(
        launcher_id="terminal",
        name="Terminal",
        target="dom0",
        user="user",
        dispvm=False,
        command="terminal",
        run_in_terminal=False,
        shutdown_on_exit_0=False,
    )


def autostart_spec() -> LauncherSpec:
    """Synthetic row that runs every launcher marked autostart: True."""
    # This is not a real VM launcher.  It only gives the human one obvious rofi
    # entry for the batch action while keeping the same two-column row layout.
    return LauncherSpec(
        launcher_id="autostart",
        name="autostart",
        target=AUTOSTART_TARGET,
        user="users",
        dispvm=False,
        command="autostart",
        run_in_terminal=False,
        shutdown_on_exit_0=False,
    )


def launcher_icon_key(kuhb_dir: Path | None, spec: LauncherSpec) -> str:
    """Prefer kuhb-local launcher SVGs; fall back to the shared icon id."""
    # rofi_common accepts either an icon file path or an icon theme key.  KUHBs can
    # ship per-launcher SVGs, while shared icons use the launcher id as the key.
    if spec.target == "dom0":
        return str(DOM0_TERMINAL_ICON)
    if kuhb_dir is not None:
        icon_path = kuhb_dir / "launcher-icons" / f"{spec.launcher_id}.svg"
        if icon_path.is_file():
            return str(icon_path)
    return spec.launcher_id


def is_disposable(value: bool) -> bool:
    """Show disposable launchers explicitly in the command column."""
    return value is True


def command_label(spec: LauncherSpec) -> str:
    """Prefix disposable launchers inside the command column."""
    # Disposable launchers still target the template VM name in qvm-run, so the
    # text label makes the --dispvm behavior visible before the user clicks.
    prefix = "(Disp) " if is_disposable(spec.dispvm) else ""
    return f"{prefix}{spec.command}"


def launcher_plain_label(spec: LauncherSpec) -> str:
    """Build two text columns: command and user@vm."""
    # The plain label is not shown directly when markup is enabled.  Its length is
    # passed to rofi_common so rofi can keep matching/filtering aligned with the
    # visible two-column markup row.
    where = f"{spec.user}@{spec.target}"
    return f"{command_label(spec):<34}  {where:<28}"


def launcher_markup_label(spec: LauncherSpec, color: str) -> str:
    """Color two text columns by VM, with root highlighted inside user@vm."""
    where = f"{spec.user}@{spec.target}"
    command_cell = f"{command_label(spec):<34}"
    # Escape command text because it is inserted into Pango markup.  Padding stays
    # inside the colored span so both columns keep a stable visual width.
    pieces = [f'<span foreground="{color}">{html.escape(command_cell)}  </span>']

    if spec.user == "root":
        # Root launchers are rare and dangerous enough to highlight separately, but
        # the rest of user@target should keep the normal VM label color.
        if len(where) > 28:
            die(f"launcher user@target field is too long: {where}")
        suffix = f"@{spec.target}" + " " * (28 - len(where))
        pieces.append(f'<span foreground="#e53935"><b>root</b></span><span foreground="{color}">{html.escape(suffix)}</span>')
    else:
        # Non-root rows can be escaped as one padded string because no nested markup
        # is needed inside the user@target column.
        pieces.append(f'<span foreground="{color}">{html.escape(f"{where:<28}")}</span>')

    return "".join(pieces)


def load_launcher_specs() -> tuple[dict, list[tuple[LauncherSpec, Path | None]], dict[str, str]]:
    """Read installed kuhb.yml files directly; no generated launcher cache."""
    # KUHBS core keeps common defaults in defaults.yml.  Raw kuhb.yml files only
    # contain user overrides, so launcher_specs()/resolve_kuhs() need defaults to
    # compute the final VM names, labels, and launcher settings.
    defaults = load_defaults(repo_defaults_path())

    # dom0 is not managed by KUHBS, but it is useful enough to always show one
    # local terminal row next to the per-VM launchers.
    specs: list[tuple[LauncherSpec, Path | None]] = [(dom0_terminal_spec(), None)]
    labels: dict[str, str] = {}

    for definition_path in sorted(KUHBS_ROOT.glob("*/kuhb.yml")):
        # Each installed KUHB directory owns one kuhb.yml and optional icon files.
        # Keep definition_path.parent with every spec so icon lookup remains local
        # to the KUHB that defined the launcher.
        definition = load_yaml(definition_path)

        # launcher_specs() returns normalized command specs attached to concrete VM
        # names such as app-signal or ndp-geforce-now.  It hides the details of the
        # KUHBS app/ndp/sta YAML shapes from this desktop integration script.
        specs.extend((spec, definition_path.parent) for spec in launcher_specs(defaults, definition))

        # The menu colors are based on each resolved VM's Qubes label.  Build a
        # target-name -> label map once so build_rows() can color rows cheaply.
        for kuh in resolve_kuhs(defaults, definition):
            label = kuh.config.get("prefs", {}).get("label")
            if label:
                labels[kuh.name] = str(label).lower()
    return defaults, specs, labels


def color_for_launcher_target(vm: str, labels: dict[str, str]) -> str:
    """Convert the kuhb.yml label into the hex color used by menu rows."""
    if vm in {"dom0", AUTOSTART_TARGET}:
        return "#f5f2ff"
    # Non-dom0 rows should have been produced by resolve_kuhs(), so a missing label
    # means the installed KUHB definition is incomplete rather than something to
    # silently color with a fallback.
    label = labels[vm]
    return LABEL_COLORS[label]


def build_rows() -> tuple[dict, list[RofiRow], list[LauncherSpec]]:
    """Read qubes.xml once, then show launchers for created VMs."""
    # Reading qubes.xml avoids spawning qvm-ls for every launcher.  The file is the
    # local dom0 source of truth for which named VMs already exist.
    existing_vms = read_qubes_xml_names()
    defaults, specs, labels = load_launcher_specs()
    rows: list[RofiRow] = []
    launchers: list[LauncherSpec] = []
    # Always show the pseudo-launcher, even when no real autostart launcher is
    # currently runnable.  Selecting it then just loops over an empty list.
    pseudo = autostart_spec()
    plain = launcher_plain_label(pseudo)
    rows.append(RofiRow(label=launcher_markup_label(pseudo, color_for_launcher_target(pseudo.target, labels)), icon_key="kuhbs", meta="autostart", plain_length=len(plain)))
    launchers.append(pseudo)
    for spec, kuhb_dir in specs:
        # KUHB definitions may exist before their VMs are created.  Hide those rows
        # so clicking a launcher never starts qvm-run against a non-existent target.
        if spec.target != "dom0" and spec.target not in existing_vms:
            continue
        plain = launcher_plain_label(spec)
        color = color_for_launcher_target(spec.target, labels)
        label = launcher_markup_label(spec, color)
        # rows and launchers are parallel lists: rofi returns the selected row index,
        # and that same index retrieves the LauncherSpec to execute.
        rows.append(RofiRow(label=label, icon_key=launcher_icon_key(kuhb_dir, spec), meta=f"{spec.target}-{spec.launcher_id}", plain_length=len(plain)))
        launchers.append(spec)
    return defaults, rows, launchers


def terminal_exec_command(defaults: dict, spec: LauncherSpec, command: str) -> str:
    """Build the xfce4-terminal command used for terminal launchers."""
    terminal = defaults["terminal"]
    title = f"{spec.target}: {spec.name}"

    # Launcher VMs are KUHBS-managed, so xfce4-terminal is part of the VM contract.
    # xfce4-terminal execs --command directly, so shell builtins like `set` need bash.
    shell_command = shlex.join(["bash", "-lc", command])
    args = [terminal["path"], *terminal["args"], "--title", title, "--command", shell_command]
    return shlex.join(args)


def qvm_run_command(defaults: dict, spec: LauncherSpec) -> str:
    """Build the VM-side command string for qvm-run."""
    command = launcher_command(defaults, spec)

    # shutdown_on_exit_0 is implemented inside the VM.  That lets the app decide
    # whether it exited cleanly before sudo powers the qube down.
    if spec.shutdown_on_exit_0:
        command = f"{command} && /usr/bin/sudo --non-interactive /sbin/shutdown -h now"

    if spec.run_in_terminal:
        # Terminal wrapping should follow KUHBS defaults.yml instead of carrying a
        # separate xterm policy in the i3/rofi integration.
        inner = f"set -x; {command} || cat"
        return terminal_exec_command(defaults, spec, inner)
    return command


def launch(defaults: dict, spec: LauncherSpec) -> None:
    """Run the selected launcher directly."""
    if spec.target == "dom0":
        # dom0 terminal setup lives in the KUHBS CLI, not in qvm-run.  Detach the
        # process so closing rofi does not keep a useless parent process around.
        subprocess.Popen(["/usr/bin/kuhbs", "terminal", "dom0"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        return

    # qvm-run gets argv as a list so Python handles dom0-side argument boundaries.
    # The guest command itself is one string because qvm-run executes that inside
    # the target VM.
    args = ["/usr/bin/qvm-run", "--user", spec.user]
    if spec.dispvm:
        # --dispvm means spec.target is the disposable template, not the final
        # runtime VM name.  Qubes creates and names the disposable instance.
        args.append("--dispvm")
    args.extend([spec.target, qvm_run_command(defaults, spec)])
    subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def launch_autostart(defaults: dict, launchers: list[LauncherSpec]) -> None:
    """Run each visible launcher marked autostart: True."""
    # KISS: no waiting, retrying, batching, status checks, or special subprocess
    # behavior.  Each real launcher is fired exactly like selecting that row by hand.
    autostart_launchers = [spec for spec in launchers if spec.autostart is True]
    if not autostart_launchers:
        subprocess.Popen(["notify-send", "KUHBS", "No autostart launchers configured"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        return
    for spec in autostart_launchers:
        launch(defaults, spec)


def main() -> None:
    """Show launchers from kuhb.yml and run the selected launcher."""
    defaults, rows, launchers = build_rows()
    # rofi_dmenu returns None when the user cancels, otherwise it returns the index
    # of the selected row from the rows list built above.
    selected = rofi_dmenu(
        rows,
        "Type to filter launchers",
        extra_args=["-hover-select", "-me-select-entry", "", "-me-accept-entry", "MousePrimary"],
    )
    if selected is None:
        return
    if launchers[selected].launcher_id == "autostart" and launchers[selected].target == AUTOSTART_TARGET:
        launch_autostart(defaults, launchers)
        return
    launch(defaults, launchers[selected])


if __name__ == "__main__":
    main()
