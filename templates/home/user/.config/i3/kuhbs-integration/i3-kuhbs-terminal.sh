#!/bin/bash
#
# Spawn a xfce4-terminal in the VM that is currently the active window
# First argument is the VM-side user for qvm-run

set -e



# Process arguments
terminal_user=$1


# Get i3wm id of the focused window
get_id() {
    local id=$(xprop -root _NET_ACTIVE_WINDOW)
    echo ${id##* } # extract id
}

# Get the VM name
get_vm() {
    local id=$(get_id)
    local vm=$(xprop -id $id | grep '_QUBES_VMNAME(STRING)')
    local vm=${vm#*\"} # extract vmname
    echo ${vm%\"*} # extract vmname
}

# run terminal in focused VM
if [[ -n "$(get_vm)" ]]; then
    qvm-run --user "$terminal_user" "$(get_vm)" "xfce4-terminal --hide-menubar --hide-borders --hide-toolbar --hide-scrollbar" &

# run terminal in dom0
else
    xfce4-terminal --hide-menubar --hide-borders --hide-toolbar --hide-scrollbar &

fi
