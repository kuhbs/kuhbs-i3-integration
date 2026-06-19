#!/bin/bash
#
# "Automatically" copy paste in Qubes OS with a i3 keybind

echo "This script is much more confusing to use than just copy.sh and paste.sh"
exit 1

set -e -x



notify-send "Copying VM copy buffer into Qubes copy buffer"

# Not sure why this sleep 0.5 is required, but without it the crtl+shift+c does nothing
sleep 1
xdotool key Control_L+Shift_L+c

notify-send "pasting in 3 seconds"; sleep 1
notify-send "pasting in 2 seconds"; sleep 1
notify-send "pasting in 1 seconds"; sleep 1
notify-send "pasting"

xdotool key Control_L+Shift_L+v

xdotool click 2
