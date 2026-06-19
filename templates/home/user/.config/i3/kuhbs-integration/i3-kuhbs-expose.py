#!/usr/bin/env python3

"""KUHBS rofi expose/window switcher."""

from __future__ import annotations

import html
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterator

# rofi_common is copied by this i3 integration repo, not installed globally.
# Adding it to sys.path lets the script run directly from an i3 keybind.
sys.path.insert(0, str(Path.home() / ".kuhbs/rofi/lib/python"))

from rofi_common import RofiRow, clean, color_for_vm, die, fit, read_qvm_labels, rofi_dmenu, run_text


def is_polybar_window(klass: str, instance: str, title: str) -> bool:
    """Hide panels and infrastructure windows from the app switcher."""
    return any("polybar" in field.lower() for field in (klass, instance, title))


def walk_i3_tree(node: dict[str, Any], workspace: str = "") -> Iterator[dict[str, Any]]:
    """Walk the nested i3 tree and yield real app windows."""
    # i3's tree is recursive: outputs contain workspaces, workspaces contain split
    # containers, and containers eventually contain real X11 windows.  Carry the
    # current workspace name down the recursion so each yielded row can show it.
    if node.get("type") == "workspace":
        workspace = str(node.get("name") or "")

    if node.get("window"):
        # Qubes sets the X11 class to VM:application for VM windows.  dom0 windows
        # usually have a normal class without a colon, so they get vm="dom0" below.
        props = node.get("window_properties") or {}
        klass = str(props.get("class") or "")
        instance = str(props.get("instance") or "")
        title = str(node.get("name") or "")

        if not is_polybar_window(klass, instance, title):
            if ":" in klass:
                vm, app = klass.split(":", 1)
            else:
                # Non-Qubes windows are dom0 windows, not blank-VM rows.
                vm, app = "dom0", klass

            yield {
                "con_id": str(node.get("id") or ""),
                "workspace": workspace,
                "vm": vm,
                "app": app,
                "title": title,
                "urgent": bool(node.get("urgent")),
            }

    for child in node.get("nodes", []) + node.get("floating_nodes", []):
        yield from walk_i3_tree(child, workspace)


def read_windows() -> list[dict[str, Any]]:
    """Ask i3 for the current tree and return switchable windows."""
    try:
        tree = json.loads(run_text(["/usr/bin/i3-msg", "-t", "get_tree"]))
    except json.JSONDecodeError as exc:
        die(f"i3 returned invalid JSON: {exc}")
    return list(walk_i3_tree(tree))


def row_for_window(window: dict[str, Any], labels: dict[str, str]) -> RofiRow:
    """Build one rofi row for one i3 window."""
    # Validate the small dict returned by walk_i3_tree() before formatting it.  A
    # clear error is better than rofi showing a broken row or focusing the wrong id.
    for key in ("con_id", "workspace", "vm", "app", "title"):
        if window.get(key) is None:
            die(f"missing required i3 window field: {key}")

    color = color_for_vm(clean(window["vm"]), labels)

    # Keep the plain row in stable tab-separated columns.  rofi searches this text,
    # while the markup label below only adds color around the same content.
    plain = f"{fit(window['app'], 20)}	{fit(window['title'], 70)}	{fit(window['workspace'], 10)}	{clean(window['vm'])}"

    # Urgent rows use rofi's red row background, so keep text plain there
    if window["urgent"]:
        label = html.escape(plain)
    else:
        label = f'<span foreground="{color}">{html.escape(plain)}</span>'

    return RofiRow(
        label=label,
        # Use the app/class only, not the title, so random title words do not steal icons
        icon_key=clean(window["app"]),
        meta=window["con_id"],
        plain_length=len(plain),
        urgent=bool(window["urgent"]),
    )


def focus_container(con_id: str) -> None:
    """Focus the selected i3 container."""
    if not con_id:
        die("empty i3 container id from selected row")
    try:
        subprocess.run(["/usr/bin/i3-msg", f'[con_id="{con_id}"] focus'], check=True, stdout=subprocess.DEVNULL)
    except FileNotFoundError:
        die("missing required command: /usr/bin/i3-msg")
    except subprocess.CalledProcessError:
        die(f"could not focus i3 container: {con_id}")


def main() -> None:
    """Show windows and focus the selected container."""
    # qvm label colors are read once because the visible window list is only a
    # snapshot.  The next keypress rebuilds rows from fresh i3/Qubes data.
    labels = read_qvm_labels()
    rows = [row_for_window(window, labels) for window in read_windows()]
    selected = rofi_dmenu(
        rows,
        "Type to filter windows",
        extra_args=["-hover-select", "-me-select-entry", "", "-me-accept-entry", "MousePrimary"],
    )
    if selected is None:
        return
    focus_container(rows[selected].meta)


if __name__ == "__main__":
    main()
