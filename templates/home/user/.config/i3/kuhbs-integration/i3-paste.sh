#!/bin/bash
#
# "Automatically" paste in Qubes OS with a i3 keybind

set -e -x



# Notify the user
notify-send "Pasting"

# If you run xdotool at the exact time you press a key, it adds the keys together
# Hence we wait 0.25 seconds for the user to release the keys
sleep 0.25

# Paste from Qubes copy buffer
xdotool key Control_L+Shift_L+v

# Middle mouse button works in termianls and everywhere else
/usr/bin/xdotool click 2
# CRTL + v does not work in terminals
#xdotool key Control_L+v
