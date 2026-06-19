#!/usr/bin/env bash

set -u

BRIGHTNESSCTL="${BRIGHTNESSCTL:-brightnessctl}"
STEP_PERCENT=10

percent() {
    "$BRIGHTNESSCTL" -m 2>/dev/null \
        | awk -F, '{ gsub(/%/, "", $4); print int($4); found=1 } END { if (!found) exit 1 }' \
        || printf '0'
}

icon_for_percent() {
    local pct="$1"
    if [ "$pct" -lt 20 ]; then
        printf '󰃚'
    elif [ "$pct" -lt 40 ]; then
        printf '󰃛'
    elif [ "$pct" -lt 60 ]; then
        printf '󰃜'
    elif [ "$pct" -lt 80 ]; then
        printf '󰃝'
    else
        printf '󰃞'
    fi
}

show() {
    local pct
    pct=$(percent)
    printf '%s\n' "$(icon_for_percent "$pct")"
}

change() {
    case "${1:-}" in
        up)   "$BRIGHTNESSCTL" set "${STEP_PERCENT}%+" >/dev/null 2>&1 || true ;;
        down) "$BRIGHTNESSCTL" set "${STEP_PERCENT}%-" >/dev/null 2>&1 || true ;;
        max)  "$BRIGHTNESSCTL" set 100% >/dev/null 2>&1 || true ;;
    esac
    show
}

case "${1:-show}" in
    up|down|max) change "$1" ;;
    show|*) show ;;
esac
