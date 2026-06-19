#!/usr/bin/python3
# Purpose: Pause opted-in KUHBS qubes when their whole i3 workspace is inactive.
# Scope: dom0 user service; no KUHBS core dependency on i3 or systemd.
#
# Mental model:
# - i3 tells us which workspace is focused.
# - Qubes window classes tell us which VM owns each visible window.
# - KUHBS YAML decides which named VMs are allowed auto-pause targets.
# - qvm-copy and shutdown get temporary inhibits so auto-pause does not freeze important work.
# - qvm-ls is the final source of truth before pausing: only STATE == Running may be paused.
#
# Why this is intentionally conservative:
# - A VM that was never focused should not be paused just because it exists in YAML.
# - A freshly-started VM gets a 60s grace period so launchers can finish opening windows.
# - A VM that is shutting down must not be paused; pausing can freeze shutdown forever.
# - Every pause is delayed after unfocus, then re-checked against current Qubes state.
from __future__ import annotations

import json
import re
import select
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Iterable

import yaml
from kuhbs.config import load_yaml
from kuhbs.model import resolve_kuhs


# Default only; defaults.yml i3_integration.notify_send_on_change overrides this at startup.
DEBUG_NOTIFY = True
# Anonymous disp1234 qubes are safe pause targets because they are user workloads.
PAUSE_ALL_DISPVMS = True
# Startup grace uses Qubes START_TIME, not daemon memory, so service restarts do not reset the timer.
STARTUP_GRACE_SECONDS = 60.0
# Unfocus grace avoids racing app window close, workspace switches, and VM-side shutdown commands.
UNFOCUS_GRACE_SECONDS = 20.0
# qvm-copy logs before qfile-unpacker is always visible, so give the receiver a short spawn window.
QFILE_UNPACKER_FIRST_SEEN_SECONDS = 3.0
# select() timeout doubles as the poll interval for qvm-copy inhibit expiry.
QFILE_UNPACKER_POLL_SECONDS = 1.0
# KUHBS user definitions live here after install; this script is a dom0 user service.
KUHBS_ROOT = Path("/home/user/.kuhbs/my-kuhbs")
# Installed systems should use /usr/share; repo checkout keeps local development working.
DEFAULTS_CANDIDATES = (
    Path("/usr/share/kuhbs/defaults.yml"),
)
# Never infer pause targets from arbitrary window names.
# These regexes keep infrastructure protected and extract VM names only from Qubes window classes.
INFRASTRUCTURE_RE = re.compile(r"^(dom0|sys-|default-dvm$|whonix-|fedora-|debian-)")
DISPVM_RE = re.compile(r"^disp[0-9]+$")
QUBES_CLASS_RE = re.compile(r"^([^:]+):")


def notify(title: str, message: str = "") -> None:
    # This is for debugging visible behavior, not for user-facing status.
    # Keep it optional because workspace switching can produce lots of transitions.
    if not DEBUG_NOTIFY:
        return
    command = ["/usr/bin/notify-send", "--expire-time=2000", title]
    if message:
        # notify-send takes the body as a second positional argument.
        command.append(message)
    # Notification failure must not break pause/unpause behavior.
    subprocess.run(command, check=False)


def notify_transition(unpause_vms: Iterable[str], pause_vms: Iterable[str]) -> None:
    # Keep one workspace transition in one loud all-caps message.
    lines = []
    unpause_targets = sorted(unpause_vms)
    pause_targets = sorted(pause_vms)
    if unpause_targets:
        lines.append(f"UN-PAUSING: {', '.join(unpause_targets)}")
    if pause_targets:
        lines.append(f"PAUSING: {', '.join(pause_targets)}")
    if not lines:
        return
    message = "\n".join(lines)
    print(message, flush=True)
    notify(message)


def run_qubes_command(command: str, vms: Iterable[str]) -> set[str]:
    # qvm-pause/qvm-unpause accept multiple VMs, so batch workspace transitions.
    # The caller passes an absolute executable path; systemd user services should not depend on PATH.
    targets = sorted(vms)
    if not targets:
        return set()
    # check=False keeps one failed qvm command from killing the daemon; the next event re-evaluates state.
    result = subprocess.run([command, *targets], check=False)
    if result.returncode != 0:
        # qvm-unpause can be a harmless no-op/failure for already-running or changing-state VMs.
        # Do not notify success unless Qubes accepted the batch command.
        return set()
    return set(targets)


def load_defaults() -> dict[str, Any]:
    # The daemon runs from dom0 user systemd.  Installed machines should find
    # /usr/share/kuhbs/defaults.yml; the checkout path keeps development runs working.
    for path in DEFAULTS_CANDIDATES:
        if path.exists():
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    return {}


def load_enabled_vms() -> set[str]:
    # Parse once at service startup; restart the user service after KUHBS YAML changes.
    defaults = load_defaults()
    enabled: set[str] = set()
    for definition_path in sorted(KUHBS_ROOT.glob("*/kuhb.yml")):
        definition = load_yaml(definition_path)

        # resolve_kuhs() expands one kuhb.yml into concrete VM objects.  For example,
        # an ndp kuhb can resolve to tpl-*, app-*, and ndp-* VM names.
        for kuh in resolve_kuhs(defaults, definition):
            # Only concrete resolved KUHs with an explicit instance opt-in are pause targets.
            # This prevents the daemon from pausing random Qubes windows just because they
            # happen to share a workspace with managed KUHBS apps.
            if kuh.config.get("i3_integration_auto_pause") is True:
                enabled.add(kuh.name)
    return enabled


def is_allowed_vm(vm: str, enabled_vms: set[str], pause_disp_vms: bool) -> bool:
    # Infrastructure qubes are never pause targets even if a bad config names them.
    if INFRASTRUCTURE_RE.match(vm):
        return False
    if DISPVM_RE.match(vm):
        return PAUSE_ALL_DISPVMS or pause_disp_vms
    return vm in enabled_vms


def walk_nodes(node: dict[str, Any]):
    # i3 stores regular containers under "nodes" and floating windows under "floating_nodes".
    # Recursing through both means floating Qubes windows count for keeping their VM awake.
    yield node
    for key in ("nodes", "floating_nodes"):
        for child in node.get(key, []):
            yield from walk_nodes(child)


def focused_workspace(root: dict[str, Any]) -> dict[str, Any] | None:
    # i3 marks the focused leaf, not always the workspace itself.
    # Carry the current parent workspace down the recursion so a focused terminal/window
    # can be mapped back to "all Qubes windows on this workspace".
    def visit(node: dict[str, Any], workspace: dict[str, Any] | None) -> dict[str, Any] | None:
        current_workspace = node if node.get("type") == "workspace" else workspace
        if node.get("focused") is True:
            return current_workspace
        for key in ("nodes", "floating_nodes"):
            for child in node.get(key, []):
                found = visit(child, current_workspace)
                if found is not None:
                    return found
        return None

    return visit(root, None)


def qubes_vms_in_node(
    node: dict[str, Any],
    enabled_vms: set[str],
    pause_disp_vms: bool,
) -> set[str]:
    vms: set[str] = set()
    for child in walk_nodes(node):
        # Qubes GUI daemon prefixes the X11 class with the VM name, e.g. "app-signal:Signal".
        # We trust that Qubes-owned class format more than title text or workspace names.
        props = child.get("window_properties")
        if not isinstance(props, dict):
            continue
        class_name = str(props.get("class", ""))
        match = QUBES_CLASS_RE.match(class_name)
        if not match:
            continue
        vm = match.group(1)
        # The window owner still must pass the YAML/disposable/infrastructure allow-list.
        if is_allowed_vm(vm, enabled_vms, pause_disp_vms):
            vms.add(vm)
    return vms


def active_workspace_vms(
    enabled_vms: set[str],
    pause_disp_vms: bool,
) -> set[str]:
    # Query the full i3 tree each time instead of trying to maintain partial state from events.
    # That is simpler and avoids edge cases where an event is missed or a window moves workspaces.
    result = subprocess.run(["/usr/bin/i3-msg", "-t", "get_tree"], check=False, capture_output=True, text=True)
    if result.returncode != 0:
        # Empty set means "do not keep anything awake from i3" for this tick; next event retries.
        print(f"i3 get_tree failed: {result.stderr.strip()}", file=sys.stderr, flush=True)
        return set()
    root = json.loads(result.stdout)
    workspace = focused_workspace(root)
    if workspace is None:
        # This should be rare, but avoids pausing based on a guessed workspace.
        return set()
    return qubes_vms_in_node(workspace, enabled_vms, pause_disp_vms)


def journal_filecopy_target(line: str, enabled_vms: set[str], pause_disp_vms: bool) -> str | None:
    # Qubes logs the selected qvm-copy destination with the qubes.Filecopy qrexec request.
    if "qubes.Filecopy" not in line:
        return None
    tokens = re.findall(r"[A-Za-z0-9_.-]+", line)
    candidates = [token for token in tokens if is_allowed_vm(token, enabled_vms, pause_disp_vms)]
    return candidates[-1] if candidates else None


def qfile_unpacker_running(vm: str) -> bool:
    # qfile-unpacker is the destination-side receiver qvm-copy starts after policy allows it.
    try:
        result = subprocess.run(
            ["/usr/bin/qvm-run", "--quiet", "--no-gui", vm, "pgrep -x qfile-unpacker >/dev/null"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=2,
        )
    except subprocess.TimeoutExpired:
        return True
    return result.returncode == 0


def copy_still_active(vm: str, first_seen_deadline: float) -> bool:
    # Give Qubes a short window to spawn qfile-unpacker after the qrexec log appears.
    if qfile_unpacker_running(vm):
        return True
    return time.monotonic() < first_seen_deadline


def qvm_runtime_info() -> dict[str, tuple[str, float | None]]:
    # START_TIME comes from Qubes, so startup grace survives daemon restarts.
    # STATE is checked immediately before pausing so transient/shutting-down VMs are skipped.
    result = subprocess.run(
        ["/usr/bin/qvm-ls", "--raw-data", "--fields", "NAME,STATE,START_TIME"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        # Fail closed for pausing: callers get no runtime info, so no pause candidate passes the gate.
        print(f"qvm-ls failed: {result.stderr.strip()}", file=sys.stderr, flush=True)
        return {}
    info: dict[str, tuple[str, float | None]] = {}
    for line in result.stdout.splitlines():
        # --raw-data uses pipe-delimited fields without table headers.
        # Running/Paused VMs usually have a float START_TIME; Halted/dom0 may use "-".
        parts = line.split("|")
        if len(parts) != 3:
            continue
        name, state, start_time = parts
        try:
            parsed_start = float(start_time) if start_time != "-" else None
        except ValueError:
            parsed_start = None
        info[name] = (state, parsed_start)
    return info


def startup_grace_deadline(vm: str, runtime_info: dict[str, tuple[str, float | None]], now: float) -> float | None:
    # Return a monotonic deadline for when this VM is old enough to pause.
    # None means "do not pause" because the VM is not exactly Running or lacks a real START_TIME.
    state, start_time = runtime_info.get(vm, ("", None))
    if state != "Running" or start_time is None:
        return None
    # START_TIME is wall-clock time from Qubes; pending pause deadlines use monotonic time.
    # Convert the remaining wall-clock grace into a monotonic deadline for stable comparisons.
    remaining = STARTUP_GRACE_SECONDS - (time.time() - start_time)
    return now if remaining <= 0 else now + remaining


def reconcile(
    desired_awake_vms: set[str],
    current_awake_vms: set[str],
    focused_once_vms: set[str],
    pending_pauses: dict[str, float],
    shutdown_inhibits: set[str],
) -> set[str]:
    # This function is the policy core.
    # desired_awake_vms: VMs that should be awake right now because they are on the focused workspace
    #                    or temporarily inhibited by qvm-copy.
    # current_awake_vms: VMs this daemon believed were awake during the previous reconcile.
    # focused_once_vms:  VMs eligible for auto-pause; startup alone does not arm auto-pause.
    # pending_pauses:   VMs that left the focused workspace and are waiting out grace timers.
    # shutdown_inhibits: VMs seen in Qubes domain-pre-shutdown; never pause them while shutdown is pending.
    now = time.monotonic()
    # Wake first, before any qvm-ls safety checks.
    # qvm-unpause is safe to try on an already-running VM, and failures return an empty set.
    # Notify only after Qubes accepts the unpause command, keeping failed/no-op wake attempts quiet.
    # Keeping this path short makes workspace focus feel instant again.
    unpause_targets = desired_awake_vms - current_awake_vms
    unpaused_vms = run_qubes_command("/usr/bin/qvm-unpause", unpause_targets)
    notify_transition(unpaused_vms, set())
    for vm in list(pending_pauses):
        # If a VM came back to the focused workspace, or Qubes started shutting it down,
        # cancel any old sleep timer instead of pausing on stale intent.
        if vm in desired_awake_vms or vm in shutdown_inhibits:
            pending_pauses.pop(vm, None)
    for vm in current_awake_vms - desired_awake_vms:
        # Only VMs that were focused at least once can be auto-paused.
        # The unfocus timer gives app shutdown/window-close logic time to run before we freeze the VM.
        if vm in focused_once_vms and vm not in shutdown_inhibits:
            pending_pauses[vm] = now + UNFOCUS_GRACE_SECONDS
    expired_pauses = {
        vm for vm, deadline in pending_pauses.items()
        if deadline <= now and vm not in desired_awake_vms
    }
    if not expired_pauses:
        # No VM is actually ready to sleep, so skip qvm-ls entirely on the fast wake path.
        return set(desired_awake_vms)
    # Pause is the dangerous direction, so only now pay for qvm-ls and verify live state/START_TIME.
    runtime_info = qvm_runtime_info()
    pause_candidates: set[str] = set()
    for vm in expired_pauses:
        # Re-check Qubes at the last possible moment.
        # This is what protects guest-side /sbin/shutdown where no domain-pre-shutdown event exists.
        deadline = startup_grace_deadline(vm, runtime_info, now)
        if deadline is None or vm in shutdown_inhibits:
            # Not exactly Running, no valid START_TIME, or Qubes says shutdown is in progress.
            # Drop it from pending instead of retrying forever.
            pending_pauses.pop(vm, None)
        elif deadline > now:
            # The VM is Running but still inside the 60s startup grace.
            # Move its pending pause to the startup deadline rather than waking every tick.
            pending_pauses[vm] = deadline
        else:
            # All gates passed: focused once, unfocused for grace, older than 60s, not shutting down, Running.
            pause_candidates.add(vm)
            pending_pauses.pop(vm, None)
    # Only pause produces a notification; wake failures/no-ops stay silent and cheap.
    notify_transition(set(), pause_candidates)
    run_qubes_command("/usr/bin/qvm-pause", pause_candidates)
    # The returned set is the daemon's new "currently awake by policy" snapshot.
    return set(desired_awake_vms)


def start_qubes_event_process() -> subprocess.Popen[str]:
    # The main daemon already uses select() on subprocess stdout for i3 and journalctl.
    # Running the asyncio qubesadmin listener as a child keeps this file single-threaded and KISS.
    # qubesadmin events catch qvm-shutdown early; guest /sbin/shutdown is still guarded by qvm-ls state.
    code = r'''
import asyncio
import sys
try:
    import qubesadmin
    import qubesadmin.events
except ImportError as exc:
    # dom0 should have qubesadmin. Exit non-zero so the parent daemon fails loud instead of
    # silently losing the qvm-shutdown inhibit path.
    print(f"qubesadmin unavailable: {exc}", file=sys.stderr, flush=True)
    raise SystemExit(1)

# Qubes() connects to the local Admin API in dom0.
app = qubesadmin.Qubes()
events = qubesadmin.events.EventsDispatcher(app)


def emit(subject, event, **kwargs):
    # Print a tiny machine-readable protocol for the parent process: "vm|event".
    # kwargs are intentionally ignored here; only the lifecycle edge matters for pause inhibits.
    name = subject.name if subject is not None else ""
    print(f"{name}|{event}", flush=True)


# domain-pre-shutdown is produced by qvm-shutdown/qubesd paths before shutdown completes.
# domain-shutdown and domain-shutdown-failed are cleanup edges for the inhibit set.
for event in ("domain-pre-shutdown", "domain-shutdown", "domain-shutdown-failed"):
    events.add_handler(event, emit)

# This call blocks forever until the event connection dies or the process is terminated.
asyncio.run(events.listen_for_events())
'''
    return subprocess.Popen(
        [sys.executable, "-u", "-c", code],
        stdout=subprocess.PIPE,
        stderr=None,
        text=True,
    )


def event_stream():
    # Watch i3 focus, qrexec Filecopy logs, and Qubes lifecycle events.
    i3_process = subprocess.Popen(
        ["/usr/bin/i3-msg", "--monitor", "-t", "subscribe", '["window","workspace"]'],
        stdout=subprocess.PIPE,
        stderr=None,
        text=True,
    )
    journal_process = subprocess.Popen(
        ["/usr/bin/journalctl", "--follow", "--lines=0", "--output=cat"],
        stdout=subprocess.PIPE,
        stderr=None,
        text=True,
    )
    qubes_process = start_qubes_event_process()
    # Popen stdout is optional in the type system; these asserts document that all three streams are required.
    assert i3_process.stdout is not None
    assert journal_process.stdout is not None
    assert qubes_process.stdout is not None
    streams = {
        i3_process.stdout: "i3",
        journal_process.stdout: "journal",
        qubes_process.stdout: "qubes",
    }
    while i3_process.poll() is None and journal_process.poll() is None:
        if qubes_process.poll() is not None:
            # Losing Qubes events means losing the early qvm-shutdown inhibit.
            # Fail loudly instead of continuing in a degraded, surprising mode.
            i3_process.terminate()
            journal_process.terminate()
            raise SystemExit(qubes_process.returncode or 1)
        # One select loop keeps all event sources serialized through the same reconcile path.
        # The timeout creates periodic "tick" events so delayed qvm-copy/pause deadlines expire.
        ready, _, _ = select.select(list(streams), [], [], QFILE_UNPACKER_POLL_SECONDS)
        if not ready:
            yield "tick", ""
            continue
        for stream in ready:
            line = stream.readline()
            if not line:
                continue
            yield streams[stream], line
    i3_process.terminate()
    journal_process.terminate()
    if qubes_process.poll() is None:
        qubes_process.terminate()
    raise SystemExit(i3_process.poll() or journal_process.poll() or 1)


def handle_qubes_event(
    line: str,
    shutdown_inhibits: set[str],
    pending_pauses: dict[str, float],
    focused_once_vms: set[str],
) -> None:
    # Lines come from start_qubes_event_process() as "vm|event".
    # Ignore malformed lines because stderr is not part of this stdout protocol.
    parts = line.strip().split("|", 1)
    if len(parts) != 2:
        return
    vm, event = parts
    if not vm:
        return
    if event == "domain-pre-shutdown":
        # qvm-shutdown reached qubesd. Cancel sleeps immediately so we do not freeze shutdown.
        shutdown_inhibits.add(vm)
        pending_pauses.pop(vm, None)
    elif event in {"domain-shutdown", "domain-shutdown-failed"}:
        # Either the VM is gone or shutdown failed; in both cases this shutdown attempt is over.
        shutdown_inhibits.discard(vm)
        pending_pauses.pop(vm, None)
        if event == "domain-shutdown":
            # If the VM boots again later, it must be focused again before auto-pause is armed.
            focused_once_vms.discard(vm)


def reconcile_current_state(
    current_awake_vms: set[str],
    enabled_vms: set[str],
    pause_disp_vms: bool,
    copy_inhibits: dict[str, float],
    focused_once_vms: set[str],
    pending_pauses: dict[str, float],
    shutdown_inhibits: set[str],
) -> set[str]:
    # Keep all "what should be awake now?" calculation in one place.
    # The main loop calls this after each event and after qvm-copy inhibit cleanup.
    workspace_vms = active_workspace_vms(enabled_vms, pause_disp_vms)
    # Focusing a workspace arms every allowed VM on that workspace for future auto-pause.
    focused_once_vms.update(workspace_vms)
    # qvm-copy targets are treated like focused VMs while their receiver is still active.
    desired_awake_vms = workspace_vms | set(copy_inhibits)
    return reconcile(
        desired_awake_vms,
        current_awake_vms,
        focused_once_vms,
        pending_pauses,
        shutdown_inhibits,
    )


def main() -> int:
    global DEBUG_NOTIFY
    defaults = load_defaults()
    i3_defaults = defaults.get("i3_integration", {}) if isinstance(defaults.get("i3_integration"), dict) else {}
    # Keep notifications tunable from KUHBS defaults without editing the daemon.
    DEBUG_NOTIFY = bool(i3_defaults.get("notify_send_on_change", DEBUG_NOTIFY))
    pause_disp_vms = bool(i3_defaults.get("pause_disp_vms"))
    enabled_vms = load_enabled_vms()
    if not enabled_vms and not (pause_disp_vms or PAUSE_ALL_DISPVMS):
        print(
            f"No KUHBS auto-pause targets: found no instance with i3_integration_auto_pause: True under {KUHBS_ROOT} "
            "and DisposableVM auto-pause is disabled.",
            flush=True,
        )
    current_awake_vms: set[str] = set()
    focused_once_vms: set[str] = set()
    pending_pauses: dict[str, float] = {}
    shutdown_inhibits: set[str] = set()
    copy_inhibits: dict[str, float] = {}
    # Initial reconcile intentionally does NOT pause every YAML-enabled VM.
    # It only records whatever is already on the focused workspace as awake/focused-once.
    current_awake_vms = reconcile_current_state(
        current_awake_vms,
        enabled_vms,
        pause_disp_vms,
        copy_inhibits,
        focused_once_vms,
        pending_pauses,
        shutdown_inhibits,
    )
    for event_kind, event_line in event_stream():
        if event_kind == "journal":
            # qvm-copy target appears in qrexec logs before the destination-side unpacker is stable.
            # Add an inhibit immediately, then qfile_unpacker_running() will decide when it is safe to drop.
            target = journal_filecopy_target(event_line, enabled_vms, pause_disp_vms)
            if target is not None:
                copy_inhibits[target] = time.monotonic() + QFILE_UNPACKER_FIRST_SEEN_SECONDS
        elif event_kind == "qubes":
            # Qubes lifecycle events update shutdown inhibits before any pause decisions are made.
            handle_qubes_event(event_line, shutdown_inhibits, pending_pauses, focused_once_vms)
        # First reconcile reacts to the incoming event immediately.
        current_awake_vms = reconcile_current_state(
            current_awake_vms,
            enabled_vms,
            pause_disp_vms,
            copy_inhibits,
            focused_once_vms,
            pending_pauses,
            shutdown_inhibits,
        )
        # This second reconcile is only for qvm-copy inhibit expiry, not normal workspace switching.
        # A plain workspace switch gets one i3 event; any PAUSING+UN-PAUSING chatter comes from one
        # state transition containing two action groups, not from parsing two log lines.
        copy_inhibits = {
            vm: deadline for vm, deadline in copy_inhibits.items() if copy_still_active(vm, deadline)
        }
        # Second reconcile applies qvm-copy inhibit expiry from the cleanup step above.
        current_awake_vms = reconcile_current_state(
            current_awake_vms,
            enabled_vms,
            pause_disp_vms,
            copy_inhibits,
            focused_once_vms,
            pending_pauses,
            shutdown_inhibits,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
