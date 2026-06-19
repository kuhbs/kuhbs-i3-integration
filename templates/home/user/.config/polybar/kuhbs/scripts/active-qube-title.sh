#!/usr/bin/env bash

# Polybar active Qubes window title module.
# Prints a rounded pill whose color follows the active qube's qvm-label.
# Output format:
#   qube-name | window-title

set -u

BAR_BG="#1F1F1F"
TEXT_FG="#FFFFFF"
MENU_BG="#6400A8"
LEFT_STATUS_BG="#2592EA"
DESKTOP_FG="#FFFFFF"
DESKTOP_BG="#4A4A4A"
UNKNOWN_BG="#555555"
MAX_TITLE_LEN=12

# Qubes i3 focused titlebar colors from QubesOS/qubes-desktop-linux-i3
# 0001-Show-qubes-domain-in-configurable-colored-borders.patch.
label_color() {
    case "${1,,}" in
        red)    printf '#bd2727' ;;
        orange) printf '#e79e27' ;;
        yellow) printf '#e7e532' ;;
        green)  printf '#5ad840' ;;
        gray|grey) printf '#8e8e95' ;;
        blue)   printf '#3874d8' ;;
        purple) printf '%s' "$MENU_BG" ;;
        black)  printf '#333333' ;;
        *)      printf '%s' "$UNKNOWN_BG" ;;
    esac
}

label_text_color() {
    case "${1,,}" in
        orange|yellow|green) printf '#000000' ;;
        *)                   printf '%s' "$TEXT_FG" ;;
    esac
}

# Extract the first quoted string from xprop output.
xprop_quoted_value() {
    sed -n 's/^[^"]*"\(.*\)"[^"]*$/\1/p' | head -n 1
}

polybar_escape() {
    # Avoid accidental Polybar formatting injection from window titles.
    # The most important sequence to neutralize is "%{".
    printf '%s' "$1" | sed 's/%{/%%{/g; s/[[:cntrl:]]//g'
}

truncate() {
    local s="$1"
    local max="$2"
    if [ "${#s}" -gt "$max" ]; then
        printf '%s…' "${s:0:$((max-1))}"
    else
        printf '%s' "$s"
    fi
}

get_active_window() {
    xprop -root _NET_ACTIVE_WINDOW 2>/dev/null \
        | sed -n 's/.*window id # \(0x[0-9a-fA-F]*\).*/\1/p'
}

get_window_title() {
    local win="$1"
    local title

    title=$(xprop -id "$win" _NET_WM_NAME 2>/dev/null | xprop_quoted_value || true)
    if [ -z "$title" ]; then
        title=$(xprop -id "$win" WM_NAME 2>/dev/null | xprop_quoted_value || true)
    fi

    printf '%s' "$title"
}

get_qube_name() {
    local win="$1"
    local vm

    # Qubes GUI windows normally expose this property in dom0.
    vm=$(xprop -id "$win" _QUBES_VMNAME 2>/dev/null | xprop_quoted_value || true)

    # Fallback for some setups/tools that expose the VM name differently.
    if [ -z "$vm" ]; then
        vm=$(xprop -id "$win" _QUBES_VMNAME 2>/dev/null \
            | sed -n 's/.*= *\([^ ]\+\).*/\1/p' \
            | tr -d '"' \
            | head -n 1 || true)
    fi

    printf '%s' "$vm"
}

get_qube_label() {
    local vm="$1"
    local label=""

    if [ -n "$vm" ] && command -v qvm-prefs >/dev/null 2>&1; then
        label=$(qvm-prefs "$vm" label 2>/dev/null | head -n 1 || true)
    fi

    printf '%s' "$label"
}

print_pill() {
    local bg="$1"
    local fg="$2"
    local text="$3"

    # Draw status-to-title cap, text, then title-to-bar cap.
    printf '%%{T2}%%{F%s}%%{B%s}%%{T-}%%{F%s}%%{B%s} %s %%{T2}%%{F%s}%%{B%s}%%{T-}\n' \
        "$LEFT_STATUS_BG" "$bg" "$fg" "$bg" "$text" "$bg" "$BAR_BG"
}

main() {
    local win vm label bg fg title text

    win=$(get_active_window)

    if [ -z "$win" ] || [ "$win" = "0x0" ]; then
        print_pill "$DESKTOP_BG" "$DESKTOP_FG" "dom0"
        exit 0
    fi

    vm=$(get_qube_name "$win")
    title=$(get_window_title "$win")

    vm=$(polybar_escape "$vm")
    title=$(polybar_escape "$title")
    title=$(truncate "$title" "$MAX_TITLE_LEN")

    if [ -n "$vm" ]; then
        label=$(get_qube_label "$vm")
        bg=$(label_color "$label")
        fg=$(label_text_color "$label")
        text="$vm"
    else
        bg="$DESKTOP_BG"
        fg="$DESKTOP_FG"
        text="dom0"
    fi

    print_pill "$bg" "$fg" "$text"
}

main "$@"
