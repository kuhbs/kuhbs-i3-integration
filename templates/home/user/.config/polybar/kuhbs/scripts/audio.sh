#!/usr/bin/env bash

set -u

AMIXER="${AMIXER:-amixer}"
STATE_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/polybar-kuhbs"
STATE_FILE="$STATE_DIR/audio-before-zero"
STEP_PERCENT=10

status() {
    "$AMIXER" get Master 2>/dev/null \
        | awk '
            /%/ {
                if (match($0, /\[[0-9]+%\]/)) {
                    pct = substr($0, RSTART + 1, RLENGTH - 3)
                }
                if ($0 ~ /\[off\]/) muted = 1
                found = 1
            }
            END {
                if (!found) exit 1
                printf "%s %s\n", pct + 0, muted ? "muted" : "on"
            }' \
        || printf '0 muted\n'
}

read_saved_percent() {
    local pct
    if [ -r "$STATE_FILE" ]; then
        read -r pct < "$STATE_FILE" || pct=""
    fi

    case "${pct:-}" in
        ''|*[!0-9]*) return 1 ;;
    esac

    if [ "$pct" -gt 0 ] && [ "$pct" -le 100 ]; then
        printf '%s\n' "$pct"
        return 0
    fi

    return 1
}

save_percent() {
    mkdir -p "$STATE_DIR"
    printf '%s\n' "$1" > "$STATE_FILE"
}

clear_saved_percent() {
    rm -f "$STATE_FILE"
}

icon_for_percent() {
    local pct="$1"
    local muted="$2"

    if [ "$muted" = "muted" ] || [ "$pct" -eq 0 ]; then
        printf '󰝟'
    elif [ "$pct" -lt 40 ]; then
        printf '󰕿'
    elif [ "$pct" -lt 70 ]; then
        printf '󰖀'
    else
        printf '󰕾'
    fi
}

show() {
    local pct muted
    read -r pct muted <<EOF_STATUS
$(status)
EOF_STATUS

    if [ "$muted" = "muted" ]; then
        pct=0
    fi

    printf '%s\n' "$(icon_for_percent "$pct" "$muted")"
}

restore_saved() {
    local saved
    if saved=$(read_saved_percent); then
        "$AMIXER" -q set Master "${saved}%" unmute >/dev/null 2>&1 || true
        clear_saved_percent
        return 0
    fi

    return 1
}

change() {
    local pct muted
    read -r pct muted <<EOF_STATUS
$(status)
EOF_STATUS

    if [ "${1:-}" = "zero" ]; then
        if [ "$muted" = "muted" ] || [ "$pct" -eq 0 ]; then
            restore_saved || "$AMIXER" -q set Master 100% unmute >/dev/null 2>&1 || true
        else
            save_percent "$pct"
            "$AMIXER" -q set Master 0% mute >/dev/null 2>&1 || true
        fi
        show
        return
    fi

    if [ "$muted" = "muted" ] || [ "$pct" -eq 0 ]; then
        restore_saved || "$AMIXER" -q set Master 100% unmute >/dev/null 2>&1 || true
        show
        return
    fi

    clear_saved_percent
    case "${1:-}" in
        up) "$AMIXER" -q set Master "${STEP_PERCENT}%+" unmute >/dev/null 2>&1 || true ;;
        down) "$AMIXER" -q set Master "${STEP_PERCENT}%-" unmute >/dev/null 2>&1 || true ;;
    esac
    show
}

case "${1:-show}" in
    up|down|zero) change "$1" ;;
    show|*) show ;;
esac
