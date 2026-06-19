#!/usr/bin/env bash

# Event-driven wrapper for active-qube-title.sh.
# Prints immediately on startup, then whenever i3/X changes active window.

SCRIPT="${HOME}/.config/polybar/kuhbs/scripts/active-qube-title.sh"

print_title() {
    "$SCRIPT"
}

print_title

# React immediately to focus changes instead of waiting for a polling interval.
# If xprop exits, sleep briefly and restart so Polybar does not lose the module.
while true; do
    xprop -spy -root _NET_ACTIVE_WINDOW 2>/dev/null | while IFS= read -r _; do
        print_title
    done
    sleep 1
done
