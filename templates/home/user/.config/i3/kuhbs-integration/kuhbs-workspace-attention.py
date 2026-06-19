#!/usr/bin/python3
# Purpose: mark configured KUHBS i3 workspaces urgent when a running VM asks for attention.
# Scope: dom0 user service; config is loaded once, so restart the service after YAML changes.
from __future__ import annotations

import json
import shlex
import subprocess
import time
from pathlib import Path
from typing import Any

from kuhbs.config import load_defaults, load_yaml, repo_defaults_path
from kuhbs.model import resolve_kuhs

KUHBS_ROOT = Path("/home/user/.kuhbs/my-kuhbs")
ATTENTION_FILE = "/home/user/.i3-kuhbs-workspace-attention"
POLL_SLEEP_SECONDS = 2


def load_targets() -> dict[str, str]:
    # Reuse KUHBS' YAML/name resolver so this daemon does not reimplement KUHBS shapes.
    # Defaults are required because raw kuhb.yml files omit many inherited values.
    defaults = load_defaults(repo_defaults_path())
    targets: dict[str, str] = {}
    for definition_path in sorted(KUHBS_ROOT.glob("*/kuhb.yml")):
        definition = load_yaml(definition_path)

        # Each resolved KUH is a concrete VM name plus merged config.  The attention
        # setting belongs to an instance, not just the high-level kuhb definition.
        for kuh in resolve_kuhs(defaults, definition):
            # Attention is disabled unless a concrete instance defines a workspace.
            if "i3_integration_workspace_attention" not in kuh.config:
                continue
            # This must be a workspace string; True is invalid and fails here.
            workspace = kuh.config["i3_integration_workspace_attention"].strip()
            assert workspace, f"empty workspace attention target in {definition_path}"
            targets[kuh.name] = workspace
    return targets


def vm_is_running(vm: str) -> bool:
    # qvm-check uses its exit code as the answer, so non-zero is not an exception here.
    result = subprocess.run(
        ["/usr/bin/qvm-check", "--quiet", "--running", vm],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def consume_attention_request(vm: str) -> bool:
    # Never qvm-run into halted VMs; checking the marker must not autostart qubes.
    if not vm_is_running(vm):
        return False

    # The VM-side marker is one-shot: test it, then remove it in the same shell.
    # qvm-run's exit code becomes the answer: 0 means the marker existed and was
    # consumed, non-zero means there was nothing to do this polling cycle.
    result = subprocess.run(
        [
            "/usr/bin/qvm-run",
            "--quiet",
            "--no-gui",
            vm,
            f"test -f {shlex.quote(ATTENTION_FILE)} && rm -f {shlex.quote(ATTENTION_FILE)}",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=2,
        check=False,
    )
    return result.returncode == 0


def i3_tree() -> dict[str, Any]:
    # i3 owns the workspace/window truth; fail if the daemon cannot talk to i3.
    result = subprocess.run(
        ["/usr/bin/i3-msg", "-t", "get_tree"],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def focused_workspace() -> str | None:
    # Avoid marking the current workspace urgent; the user is already looking at it.
    result = subprocess.run(
        ["/usr/bin/i3-msg", "-t", "get_workspaces"],
        capture_output=True,
        text=True,
        check=True,
    )
    for workspace in json.loads(result.stdout):
        if workspace["focused"]:
            return workspace["name"]
    return None


def walk(node: dict[str, Any]):
    # i3 nests containers, so workspace/window search has to recurse.
    yield node
    for child in node.get("nodes", []) + node.get("floating_nodes", []):
        yield from walk(child)


def workspace_window(root: dict[str, Any], workspace: str) -> str | None:
    # Urgency needs a real non-focused window; empty workspaces only get a warning.
    for node in walk(root):
        if node.get("type") != "workspace" or node.get("name") != workspace:
            continue
        for child in walk(node):
            if child.get("window") is not None and not child.get("focused"):
                return str(child["window"])
    return None


def mark_workspace_urgent(root: dict[str, Any], vm: str, workspace: str) -> None:
    # The current workspace is already visible, so no urgency marker is needed.
    if focused_workspace() == workspace:
        return
    window = workspace_window(root, workspace)
    if window is None:
        print(f"WARNING: no active window on workspace {workspace} for {vm}", flush=True)
        return
    print(f"marking workspace {workspace} urgent", flush=True)
    subprocess.run(["/usr/bin/xdotool", "set_window", "--urgency", "1", window], check=True)


def main() -> int:
    # Targets are static by design; restart the systemd user service after config edits.
    targets = load_targets()

    while True:
        root = i3_tree()

        for vm, workspace in targets.items():
            # One marker file means one urgency mark; no daemon-side alert state.
            if not consume_attention_request(vm):
                continue
            print(f"consumed attention request from {vm} for workspace {workspace}", flush=True)
            mark_workspace_urgent(root, vm, workspace)

        time.sleep(POLL_SLEEP_SECONDS)


if __name__ == "__main__":
    raise SystemExit(main())
