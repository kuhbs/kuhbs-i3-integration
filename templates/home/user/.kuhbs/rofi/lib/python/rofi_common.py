#!/usr/bin/env python3
# Purpose: Shared helpers for user-owned KUHBS rofi launchers
# Scope: Keep dom0 menu scripts small and avoid system Python installs

"""Shared helpers for the KUHBS rofi launcher and expose menus."""

from __future__ import annotations

import html
import os
import re
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path

UNIT = "\x1f"
HOME = Path.home()
THEME = HOME / ".kuhbs/rofi/kuhbs-menu.rasi"
ICON_DIR = HOME / ".kuhbs/rofi/icons"

LABEL_COLORS = {
    "red": "#e53935",
    "orange": "#fb8c00",
    "yellow": "#fdd835",
    "green": "#43a047",
    "gray": "#9e9e9e",
    "grey": "#9e9e9e",
    "blue": "#1e88e5",
    "purple": "#cc99ff",
    "black": "#f5f2ff",
}


@dataclass(frozen=True)
class RofiRow:
    """One row shown by rofi, plus metadata used after selection."""

    label: str
    icon_key: str
    meta: str
    plain_length: int
    urgent: bool = False


def die(message: str) -> None:
    """Fail loudly instead of guessing when required data is missing."""
    raise SystemExit(message)


def run_text(args: list[str]) -> str:
    """Run a required command and return stdout."""
    try:
        result = subprocess.run(args, check=True, text=True, capture_output=True)
    except FileNotFoundError:
        die(f"missing required command: {args[0]}")
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        if detail:
            die(f"command failed: {' '.join(args)}\n{detail}")
        die(f"command failed: {' '.join(args)}")
    return result.stdout


def clean(text: object) -> str:
    """Keep rofi rows one-line and searchable."""
    return " ".join(str(text).replace("\n", " ").split())


def fit(text: object, width: int) -> str:
    """Trim long fields and pad short fields so columns scan cleanly."""
    value = clean(text)
    if len(value) > width:
        return value[: max(0, width - 1)] + "…"
    return value.ljust(width)


def markup(text: str, color: str) -> str:
    """Escape user-controlled text before adding pango markup."""
    return f'<span foreground="{color}">{html.escape(text)}</span>'


def icon_path(icon_name: str) -> str:
    """Return an icon path for rofi, failing if the fallback icon is missing."""
    requested_path = Path(icon_name)
    if requested_path.is_absolute() and requested_path.is_file() and requested_path.suffix == ".svg":
        return str(requested_path)

    requested = ICON_DIR / f"{icon_name}.svg"
    if requested.is_file():
        return str(requested)

    fallback = ICON_DIR / "question.svg"
    if not fallback.is_file():
        die(f"missing required icon: {fallback}")
    return str(fallback)


def icon_for(icon_key: str) -> str:
    """Use the caller-provided icon id exactly; missing icons use question.svg."""
    return icon_path(icon_key)


def read_qvm_labels() -> dict[str, str]:
    """Read Qubes VM labels once so row colors are consistent."""
    output = run_text(["/usr/bin/qvm-ls", "--raw-data", "--fields", "NAME,LABEL"])
    labels: dict[str, str] = {}
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = [part.strip() for part in line.split("|")] if "|" in line else line.split()
        if len(parts) < 2 or parts[0].lower() == "name":
            continue
        labels[parts[0]] = parts[1].lower()
    return labels


def color_for_vm(vm: str, labels: dict[str, str]) -> str:
    """Convert a VM label name into the hex color used by menu rows."""
    if vm == "dom0":
        return "#f5f2ff"
    if vm not in labels:
        die(f"missing qvm label for VM: {vm}")
    label = labels[vm]
    if label not in LABEL_COLORS:
        die(f"unknown qvm label for VM {vm}: {label}")
    return LABEL_COLORS[label]


def screen_size() -> tuple[int, int]:
    """Read the active monitor size from xrandr."""
    output = run_text(["/usr/bin/xrandr", "--current"])
    for line in output.splitlines():
        if " connected" not in line:
            continue
        for field in line.split():
            match = re.match(r"^(\d+)x(\d+)(?:[+-].*)?$", field)
            if match:
                return int(match.group(1)), int(match.group(2))
    die("could not read active monitor size from xrandr")


def menu_lines(row_count: int) -> int:
    """Use exact height until rows would exceed the monitor."""
    if row_count < 1:
        die("cannot size rofi menu with zero rows")
    _, height = screen_size()
    max_lines = (height - 120) // 38
    if max_lines < 1:
        die(f"monitor height too small for rofi menu: {height}")
    return min(row_count, max_lines)


def menu_width(longest_chars: int) -> int:
    """Estimate menu width from the longest visible row."""
    if longest_chars < 1:
        die("cannot size rofi menu with empty labels")
    width, _ = screen_size()
    wanted = longest_chars * 8 + 120
    wanted = max(wanted, 560)
    wanted = min(wanted, width - 80)
    if wanted < 1:
        die(f"monitor width too small for rofi menu: {width}")
    return wanted


def rofi_dmenu(rows: list[RofiRow], placeholder: str, extra_args: list[str] | None = None) -> int | None:
    """Show rows in rofi and return the selected row index."""
    if not rows:
        return None

    urgent_indexes = ",".join(str(i) for i, row in enumerate(rows) if row.urgent)
    args = [
        "/usr/bin/rofi",
        "-dmenu",
        "-i",
        "-show-icons",
        "-markup-rows",
        "-matching",
        "normal",
        "-lines",
        str(menu_lines(len(rows))),
        "-format",
        "i",
        "-p",
        "",
        "-theme",
        str(THEME),
        "-theme-str",
        f'entry {{ placeholder: "{placeholder}"; }}',
        "-theme-str",
        f"window {{ width: {menu_width(max(row.plain_length for row in rows))}px; }}",
    ]
    if urgent_indexes:
        args.extend(["-u", urgent_indexes])
    if extra_args:
        args.extend(extra_args)

    payload = b"".join(
        row.label.encode()
        + b"\0icon\x1f"
        + icon_for(row.icon_key).encode()
        + b"\0meta\x1f"
        + row.meta.encode()
        + b"\n"
        for row in rows
    )

    try:
        result = subprocess.run(args, input=payload, capture_output=True, check=False)
    except FileNotFoundError:
        die("missing required command: /usr/bin/rofi")

    selected = result.stdout.decode(errors="replace").strip()
    if not selected.isdigit():
        return None
    index = int(selected)
    if index >= len(rows):
        die(f"rofi returned invalid row index: {index}")
    return index


def source_required_var(script_path: str, var_name: str) -> str:
    """Read one required variable from a shell config through bash."""
    command = f"source {shlex.quote(script_path)}; printf '%s' \"${{{var_name}-}}\""
    try:
        result = subprocess.run(["/usr/bin/bash", "-lc", command], check=True, text=True, capture_output=True)
    except FileNotFoundError:
        die("missing required command: /usr/bin/bash")
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        if detail:
            die(f"could not source required config: {script_path}\n{detail}")
        die(f"could not source required config: {script_path}")

    value = result.stdout
    if not value:
        die(f"missing required config variable {var_name} in: {script_path}")
    return value


def exec_shell_file(path: str) -> None:
    """Run a selected shell launcher file through bash."""
    launcher = Path(path)
    if not launcher.is_file():
        die(f"missing selected launcher: {path}")
    if not os.access(launcher, os.R_OK):
        die(f"selected launcher is not readable: {path}")

    # KUHBS launcher files are shell lines, not standalone shebang scripts
    os.execv("/usr/bin/bash", ["/usr/bin/bash", str(launcher)])
