#!/usr/bin/env bash

set -u

REDSHIFT="${REDSHIFT:-redshift}"
STATE_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/polybar-kuhbs"
STATE_FILE="$STATE_DIR/redshift-step"
MIN_STEP=0
MAX_STEP=100
CLICK_STEPS=10
DEFAULT_TEMP=6500
WARMEST_TEMP=2500

read_step() {
    local step
    if [ -r "$STATE_FILE" ]; then
        read -r step < "$STATE_FILE" || step="$MIN_STEP"
    else
        step="$MIN_STEP"
    fi

    case "$step" in
        ''|*[!0-9]*) step="$MIN_STEP" ;;
    esac

    if [ "$step" -lt "$MIN_STEP" ]; then
        step="$MIN_STEP"
    elif [ "$step" -gt "$MAX_STEP" ]; then
        step="$MAX_STEP"
    fi

    printf '%s\n' "$step"
}

write_step() {
    mkdir -p "$STATE_DIR"
    printf '%s\n' "$1" > "$STATE_FILE"
}

temp_for_step() {
    local step="$1"
    printf '%s\n' $((DEFAULT_TEMP - ((DEFAULT_TEMP - WARMEST_TEMP) * step / MAX_STEP)))
}

icon_for_step() {
    local step="$1"

    # Higher step means warmer/redder output, so draw a fuller thermometer
    if [ "$step" -lt 20 ]; then
        printf ''
    elif [ "$step" -lt 40 ]; then
        printf ''
    elif [ "$step" -lt 60 ]; then
        printf ''
    elif [ "$step" -lt 80 ]; then
        printf ''
    else
        printf ''
    fi
}

show() {
    printf '%s\n' "$(icon_for_step "$(read_step)")"
}

apply_step() {
    local step temp
    step="$1"
    temp=$(temp_for_step "$step")
    "$REDSHIFT" -P -O "$temp" >/dev/null 2>&1 || true
    write_step "$step"
    show
}

change() {
    local step
    step=$(read_step)

    case "${1:-}" in
        up) step=$((step - CLICK_STEPS)) ;;
        down) step=$((step + CLICK_STEPS)) ;;
        cooler) step=$((step - CLICK_STEPS)) ;;
        warmer) step=$((step + CLICK_STEPS)) ;;
    esac

    if [ "$step" -lt "$MIN_STEP" ]; then
        step="$MIN_STEP"
    elif [ "$step" -gt "$MAX_STEP" ]; then
        step="$MAX_STEP"
    fi

    apply_step "$step"
}

case "${1:-show}" in
    up) change up ;;
    down) change down ;;
    cooler) change cooler ;;
    warmer) change warmer ;;
    reset) apply_step "$MIN_STEP" ;;
    show|*) show ;;
esac
