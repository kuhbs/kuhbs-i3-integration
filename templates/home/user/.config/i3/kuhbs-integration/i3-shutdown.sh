#!/bin/bash
#
# Shutdown the VM of the currently active window

set -e -x



# Process arguments
if ! [[ -z "$1" ]]; then
    target_vm=$1
    if ! qvm-ls --quiet --fields name "$target_vm" 2>&1 >/dev/null; then
        echo "Error, no such VM: $target_vm, aborting!"
    fi
fi



get_id() {
    local id=$(xprop -root _NET_ACTIVE_WINDOW)
    echo ${id##* } # extract id
}

get_vm() {
    local id=$(get_id)
    local vm=$(xprop -id $id | grep '_QUBES_VMNAME(STRING)')
    local vm=${vm#*\"} # extract vmname
    echo ${vm%\"*} # extract vmname
}

main() {
    local vm=$(get_vm)
    if [[ -n "$vm" ]] && [[ -z "$target_vm" ]]; then
        qvm-shutdown "$vm"
    # run terminal in VM given as argument
    elif ! [[ -z "$target_vm" ]] && [[ "$target_vm" != "dom0" ]]; then
        qvm-shutdown "$target_vm"
    fi
}

main
