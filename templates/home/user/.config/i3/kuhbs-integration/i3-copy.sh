#!/bin/bash
#
# "Automatically" copy in Qubes OS with a i3 keybind

set -e -x



# Notify the user
notify-send "Copying"

# If you run xdotool at the exact time you press a key, it adds the keys together
# Hence we wait 0.25 seconds for the user to release the keys
sleep 0.25

# CRTL + c would abort things in terminals
#xdotool key Control_L+c

# CRTL + Shift + c to copy into Qubes copy buffer
/usr/bin/xdotool key Control_R+Shift_R+c
